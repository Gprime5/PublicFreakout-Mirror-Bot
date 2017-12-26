from configparser import ConfigParser
from json import load, dump
from os import getpid, listdir, remove
from praw import Reddit
from prawcore.exceptions import RequestException, ServerError
from requests import get, post
from time import sleep, ctime, time
from youtube_dl import YoutubeDL
from youtube_dl.utils import DownloadError

import re
import subprocess

print(getpid())

# Empty youtube logger
class MyLogger():
	def debug(self, msg):
		pass

	def warning(self, msg):
		pass

	def error(self, msg):
		pass

config = ConfigParser()
config.read("praw.ini")

reddit = Reddit(**config["Reddit"])
auth = config["Streamable"]["username"], config["Streamable"]["password"]
yt = YoutubeDL({"logger": MyLogger(), "outtmpl": "Media\\output"})

with open("hashes.txt") as file:
	# Load hash file and only keep most recent 28 days
	hashes = [n for n in load(file) if n["created"] > time() - 3600 * 24 * 28]

def check_hash(submission):
	if hashes:
		while hashes[0]["created"] < time() - 3600 * 24 * 28:
			hashes.pop(0)

	for data in hashes:
		if data["video_url"] == submission.url:
			codes = [n[-5:] for n in data["links"]]

			if data["links"]:
				reply_reddit(submission, codes)

			return save("Repost", submission, codes)

def cleanup():
	for file in listdir("Media"):
		remove("Media/" + file)

def combine_media():
	command = [
		"ffmpeg",
		"-v", "quiet",
		"-i", "Media\\video",
		"-i", "Media\\audio",
		"-c", "copy",
		"-f", "mp4",
		"Media\\output",
		"-y"
	]

	subprocess.run(command, creationflags=8)

def download(filename, url):
	with open("Media/" + filename, "wb") as file:
		file.write(get(url).content)			

def process(submission):
	if check_hash(submission):
		return

	# Twitter post
	if "twitter" in submission.url:
		try:
			description = yt.extract_info(submission.url, process=False)["description"]
		except:
			return save("Video not found", submission)

		search = re.search("https://t.co/\w+", description)
		if search:
			submission.url = search.group()

	# Reddit hosted video
	if submission.domain == "v.redd.it":
		# If post is crosspost, set submission to linked post
		if submission.media is None:
			submission = reddit.submission(submission.crosspost_parent[3:])

		video_url = submission.media["reddit_video"]["fallback_url"]
		download("video", video_url)

		if submission.media["reddit_video"]["is_gif"]:
			code = upload("video", submission.title)
		else:
			audio_url = video_url.rsplit("/", 1)[0] + "/audio"
			download("audio", audio_url)
			combine_media()

			code = upload("output", submission.title)

		status = wait_completed(code)

		if status == "Complete":
			reply_reddit(submission, (code,))
			return save(status, submission, (code,))

	# Import from url to streamable

	url = "https://api.streamable.com/import"
	parameters = {
		"url": submission.url,
		"title": submission.title
	}

	response = get(url, parameters, auth=auth)

	if response.status_code == 200:
		code = response.json()["shortcode"]

		status = wait_completed(code)

		if status == "Complete":
			reply_reddit(submission, (code,))
			return save(status, submission, (code,))
	elif response.status_code == 403:
		raise PermissionError
	elif response.status_code == 404:
		pass # Video not found

	# Download video

	try:
		info = yt.extract_info(submission.url, process=False)
	except DownloadError as e:
		if "This video is only available for registered users" in str(e):
			return save("Unauthorized", submission)
		elif "Unsupported URL" in str(e):
			return save("Unsupported URL", submission)
		else:
			return save(str(e).split(": ")[1], submission)

	if info.get("duration"):
		if info["duration"] < 1200:
			try:
				yt.download([submission.url])
			except DownloadError as e:
				return save(str(e).split(": ")[1], submission, (code,))

			file = [i for i in listdir("Media") if "output" in i][0]

			if info["duration"] < 600:
				code = upload(file, submission.title)

				status = wait_completed(code)

				if status == "Complete":
					reply_reddit(submission, (code,))
					return save(status, submission, (code,))
			else:
				parts = int(info["duration"] // 600 + 1)

				for part in range(parts):
					command = [
						"ffmpeg",
						"-v", "quiet",
						"-ss", str(info["duration"] * part // parts),
						"-i", "Media/" + file,
						"-t", str(info["duration"] * (part + 1) // parts),
						"-c", "copy",
						"-f", "mp4",
						"Media/{}{}".format(part, file),
						"-y"
					]

					subprocess.run(command)

				codes = []
				for part in range(parts):
					filename = "{}{}".format(part, file)
					video_title = "{} [Part {}]".format(submission.title, part + 1)
					codes.append(upload(filename, video_title))

				for code in codes:
					status = wait_completed(code)

				if status == "Complete":
					reply_reddit(submission, codes)
					return save(status, submission, codes)
		else:
			return save("Over 20 minutes", submission)
	else:
		return save("Duration not found", submission)

	save("End", submission)			

def reply_reddit(submission, codes):
	if len(codes) == 1:
		mirror_text = "[Mirror](https://streamable.com/{})  \n".format(codes[0])
	else:
		mirror_format = "[Mirror [Part {}]](https://streamable.com/{})  \n"
		mirror_text = "".join(mirror_format.format(part, code) for part, code in enumerate(codes, 1))

	submission.reply(" | ".join([
		mirror_text + "  \nI am a bot",
		"[Feedback](https://www.reddit.com/message/compose/?to=Gprime5&subject=PublicFreakout%20Mirror%20Bot)",
		"[Github](https://github.com/Gprime5/PublicFreakout-Mirror-Bot)"#,
		#"[Support me](https://www.paypal.me/gprime5)"
	]))	

def run():
	while True:
		stream = reddit.subreddit("PublicFreakout").stream.submissions(pause_after=1)

		try:
			checked = [n._extract_submission_id() for n in reddit.user.me().comments.new()]
		except RequestException:
			sleep(60)
			continue

		while True:
			cleanup()

			try:
				# Get next post
				submission = next(stream)
			except RequestException:
				# Client side error
				sleep(60)
			except ServerError:
				# Reddit side error
				sleep(60)
			except StopIteration:
				break
			else:
				if submission is None:
					continue

				if submission.is_self:
					continue

				if re.search("(?:sex|fight|naked|nude|nsfw|brawl|poop)", submission.title, 2):
					continue

				# Don't bother creating mirror for posts over a day old
				if submission.created_utc < time() - 3600 * 24:
					continue

				if submission in checked:
					continue

				try:
					process(submission)
				except PermissionError:
					return "Permission denied"

			cleanup()

def save(status, submission, codes=None):
	text = "{:<19} | " + ctime() + " | https://www.reddit.com{:<85} | {}\n"
	links = ["https://streamable.com/" + code for code in (codes or [])]

	with open(auth[0] + " log.txt", "a") as file:
		file.write(text.format(status, submission.permalink, " | ".join(links)))

	hashes.append({
		"created": int(submission.created_utc),
		"reddit": "https://www.reddit.com" + submission.permalink,
		"video_url": submission.url,
		"links": links
	})

	while hashes[0]["created"] < time() - 3600 * 24 * 28:
		hashes.pop(0)

	with open("hashes.txt", "w") as file:
		dump(hashes, file, indent=4, sort_keys=True)

	return True

def upload(filename, title):
	url = "https://api.streamable.com/upload"
	title = title.encode("ascii", "ignore").decode().replace('"', "'")

	with open("Media/" + filename, "rb") as file:
		files = {"file": (title, file)}

		response = post(url, files=files, auth=auth).json()["shortcode"]

	return response

def wait_completed(code):
	""" Poll video until 100% complete """

	url = "https://api.streamable.com/videos/"

	while True:
		response = get(url + code, auth=auth)

		if response.status_code == 200:
			response = response.json()

			# 0 Uploading
			# 1 Processing
			# 2 Complete
			# 3 Error

			if response["status"] == 2:
				return "Complete"
			elif response["status"] == 3:
				return response["message"]

			sleep(5)
		else:
			return response.status_code + response.text

if __name__ == "__main__":
	print(run())
