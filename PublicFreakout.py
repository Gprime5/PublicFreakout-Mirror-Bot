
from configparser import ConfigParser
from json import load, dump
from os import getpid, listdir, remove
from prawcore.exceptions import RequestException, ServerError
from requests import get, post
from time import sleep, ctime, time
from youtube_dl import YoutubeDL
from youtube_dl.utils import DownloadError

import praw
import re
import subprocess

print(getpid())

config = ConfigParser()
config.read("praw.ini")

reddit = praw.Reddit(**config["Reddit"])
auth = config["Streamable"]["username"], config["Streamable"]["password"]
output_format = re.compile("output.*")
twitter = re.compile("https://t.co/\w+")

# Empty youtube logger
class MyLogger():
	def debug(self, msg):
		pass

	def warning(self, msg):
		pass

	def error(self, msg):
		pass

yt = YoutubeDL({
	"logger": MyLogger(),
	"outtmpl": "Media\\output"
})

with open("hashes.txt") as file:
	hashes = [n for n in load(file) if n["created"] > time() - 3600 * 24 * 28]

def run():
	while True:
		stream = reddit.subreddit("PublicFreakout").stream.submissions(pause_after=1)

		try:
			recent_comments = [n._extract_submission_id() for n in reddit.user.me().comments.new()]
		except RequestException:
			sleep(30)
			continue

		while True:
			cleanup()

			try:
				# get next post
				submission = next(stream)
			except RequestException:
				# Client side error
				sleep(30)
			except ServerError:
				# Reddit side error
				sleep(30)
			except StopIteration:
				break
			else:
				if submission is None:
					continue

				if submission.is_self:
					continue

				if submission.created_utc < time() - 3600 * 24:
					continue

				if submission in recent_comments:
					continue

				try:
					process(submission)
				except PermissionError:
					return "Permission denied"

			cleanup()

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
			return response.text

def save(status, submission, codes=None):
	codes = codes or []
	text = "{:<19} | " + ctime() + " | https://www.reddit.com{:<84} | {}\n"
	links = ["https://streamable.com/" + code for code in codes]

	with open(auth[0] + " log.txt", "a") as file:
		file.write(text.format(status, submission.permalink, " | ".join(links)))

	hashes.append({
		"created": int(submission.created_utc),
		"reddit": "https://www.reddit.com" + submission.permalink,
		"video_url": submission.url,
		"links": links
	})

	with open("hashes.txt", "w") as file:
		dump(hashes, file, indent=4, sort_keys=True)

def download(filename, url):
	with open("Media/" + filename, "wb") as file:
		file.write(get(url).content)			

def upload(filename, title):
	url = "https://api.streamable.com/upload"
	title = title.encode("ascii", "backslashreplace").decode().replace('"', "'")

	with open("Media/" + filename, "rb") as file:
		files = {"file": (title, file)}

		response = post(url, files=files, auth=auth).json()["shortcode"]

	return response

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

def cleanup():
	for file in listdir("Media"):
		remove("Media/" + file)

def reply_reddit(submission, codes):
	if len(codes) == 1:
		mirror_text = "[Mirror](https://streamable.com/{})  \n".format(codes[0])
	else:
		mirror_format = "[Mirror [Part {}]](https://streamable.com/{})  \n"
		mirror_text = "".join(mirror_format.format(part, code) for part, code in enumerate(codes, 1))

	submission.reply(" | ".join([
		mirror_text + "  \nI am a bot",
		"[Feedback](https://www.reddit.com/message/compose/?to=Gprime5&subject=PublicFreakout%20Mirror%20Bot&message=https://www.reddit.com{}%0A%0A)".format(submission.permalink),
		"[Github](https://github.com/Gprime5/PublicFreakout-Mirror-Bot)"#,
		#"[Support me](https://www.paypal.me/gprime5)"
	]))

def process(submission):
	for data in hashes:
		if data["video_url"] == submission.url:
			if data["links"]:
				reply_reddit(submission, data["links"])
			return

	# Twitter post

	if "twitter" in submission.url:
		description = yt.extract_info(submission.url, process=False)["description"]
		search = twitter.search(description)
		if search:
			submission.url = search.group()

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
		status = "Video not found"

	# Reddit hosted video

	if submission.domain == "v.redd.it":
		if submission.media is None:
		 return save("Video not found", submission)

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

	# Downloadable video

	info = yt.extract_info(submission.url, process=False)

	if info.get("duration"):
		if info["duration"] < 1200:
			try:
				yt.download([submission.url])
			except DownloadError:
				return save("Bad format", submission, (code,))

			file = [i for i in listdir("Media") if "output" in i][0]

			if info["duration"] < 600:
				code = upload(file, submission.title)

				status = wait_completed(code)

				if status == "Complete":
					reply_reddit(submission, (code,))
					return save(status, submission, (code,))
			else:
				parts = info["duration"] // 600 + 1

				for part in range(parts):
					command = [
						"ffmpeg",
						"-v", "quiet",
						"-ss", str(info["duration"] * part // parts),
						"-i", "Media/" + file,
						"-t", str(info["duration"] * (part + 1) // parts),
						"-c", "copy",
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

	save(status, submission)

if __name__ == "__main__":
	print(run())
