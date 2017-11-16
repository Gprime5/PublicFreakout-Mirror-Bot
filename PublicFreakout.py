import praw
import subprocess
import re

from prawcore.exceptions import RequestException, ServerError
from requests import get, post
from os import getpid, listdir, remove
from json import load, dump
from time import sleep, ctime, time
from configparser import ConfigParser
from youtube_dl import YoutubeDL
from youtube_dl.utils import DownloadError
from hashlib import sha256

print(getpid())

config = ConfigParser()
config.read("praw.ini")

reddit = praw.Reddit(**config["Reddit"])
auth = config["Streamable"]["username"], config["Streamable"]["password"]
bad_words = re.compile("(?:sex|fight|naked|nude|brawl)")

# Empty youtube logger
class MyLogger():
	def debug(self, msg):
		pass

	def warning(self, msg):
		pass

	def error(self, msg):
		pass

class PF():
	def __init__(self):
		self.extension = "mp4"

		self.yt = YoutubeDL({
			"logger": MyLogger(),
			"outtmpl": "Media\\output.%(ext)s",
			"progress_hooks": [self._hook]
		})

		with open("hashes.txt") as file:
			self.hashes = [n for n in load(file) if n["created"] > time() - 3600 * 24 * 28]

	def _hook(self, status):
		self.extension = status["filename"].split(".")[-1]

	def run(self):
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
					# Get next post
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
					if submission:
						if submission.created_utc < time() - 3600 * 24:
							continue

						if submission.is_self:
							continue

						if bad_words.search(submission.title.lower()):
							continue

						if submission not in recent_comments:
							self.process(submission)

	def process(self, submission):
		for data in self.hashes:
			if data["video_url"] == submission.url:
				return reply_reddit(submission, data["links"])

		try:
			info = self.yt.extract_info(submission.url, process=False)
		except DownloadError:
			info = {}

		if info.get("duration"):
			if info["duration"] < 1200:
				self.yt.download([submission.url])

				hasher = sha256()

				with open("Media/output." + self.extension, "rb") as file:
					hasher.update(file.read())

				for data in self.hashes:
					if data["hash"] == hasher.hexdigest():
						return reply_reddit(submission, data["links"])

				if info["duration"] > 600:
					return self.multipart(submission, info["duration"])
				else:
					code = upload("output." + self.extension, submission.title)

					status = wait_completed(code)

					if status == "Completed":
						self.save_hash(submission, "output." + self.extension, (code,))
						return reply_reddit(submission, ("https://streamable.com/" + code,))
					else:
						return save(status, ctime(), submission.permalink, ("https://streamable.com/" + code,))
			else:
				return save("Over 20 minutes", ctime(), submission.permalink, "")

		if submission.domain == "v.redd.it":
			video_url = submission.media["reddit_video"]["fallback_url"]
			download("video", video_url)

			if submission.media["reddit_video"]["is_gif"]:
				code = upload("video", submission.title)
			else:
				audio_url = video_url.rsplit("/", 1)[0] + "/audio"
				download("audio", audio_url)
				combine_media()
				
				hasher = sha256()

				with open("Media/output", "rb") as file:
					hasher.update(file.read())

				for data in self.hashes:
					if data["hash"] == hasher.hexdigest():
						return reply_reddit(submission, data["links"])

				code = upload("output", submission.title)

			status = wait_completed(code)

			if status == "Completed":
				self.save_hash(submission, "output", (code,))
				return reply_reddit(submission, ("https://streamable.com/" + code,))
			else:
				return save(status, ctime(), submission.permalink, "https://streamable.com/" + code)

		return self.streamable_import(submission)

	def multipart(self, submission, duration):
		""" Process videos between 10 and 20 minutes """

		parts = duration // 600 + 1

		for part in range(2):
			command = [
				"Media/ffmpeg",
				"-v", "quiet",
				"-ss", str((duration * part) // parts),
				"-i", "Media/output." + self.extension,
				"-t", str((duration * (part + 1)) // parts),
				"-c", "copy",
				"Media/{}.{}".format(part, self.extension),
				"-y"
			]

			subprocess.run(command, creationflags=8)

		codes = []
		for part in range(2):
			filename = "{}.{}".format(part, self.extension)
			video_title = "{} [Part {}]".format(submission.title, part + 1)
			codes.append(upload(filename, video_title))

		for code in codes:
			status = wait_completed(code)

			if status != "Completed":
				return status

		self.save_hash(submission, "output." + self.extension, codes)

		reply_reddit(submission, ["https://streamable.com/" + code for code in codes])

	def save_hash(self, submission, filename, codes):
		hasher = sha256()

		with open("Media/" + filename, "rb") as file:
			hasher.update(file.read())

		data = {
			"created": int(submission.created_utc),
			"reddit": "https://www.reddit.com" + submission.permalink,
			"hash": hasher.hexdigest(),
			"video_url": submission.url,
			"links": ["https://streamable.com/" + code for code in codes]
		}

		self.hashes.append(data)

		with open("hashes.txt", "w") as file:
			dump(self.hashes, file, indent=4, sort_keys=True)

	def streamable_import(self, submission):
		""" Import video from submission url to streamable """

		url = "https://api.streamable.com/import"

		parameters = {
			"url": submission.url,
			"title": submission.title
		}

		response = get(url, parameters, auth=auth)

		if response.status_code == 200:
			code = response.json()["shortcode"]

			status = wait_completed(code)

			if status == "Completed":
				return reply_reddit(submission, ("https://streamable.com/" + code,))
			else:
				return save(status, ctime(), submission.permalink, "https://streamable.com/" + code)
		elif response.status_code == 403:
			return save("Permission denied", ctime(), submission.permalink, "")
		elif response.status_code == 404:
			return save("Video not found", ctime(), submission.permalink, "")

def wait_completed(code):
	""" Poll video until 100% complete """

	utl = "https://api.streamable.com/videos/"

	while True:
		response = get(url + code, auth=auth)

		if response.status_code == 200:
			response = response.jaon()

			# 0 Uploading
			# 1 Processing
			# 2 Complete
			# 3 Error

			if response["status"] == 2:
				return "Completed"
			elif response["status"] == 3:
				return response["message"]

			sleep(5)
		else:
			return response.text

def combine_media(self):
	command = [
		"Media\\ffmpeg",
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

def upload(filename, title):
	with open("Media/" + filename, "rb") as file:
		files = {"file": (title.replace("’", "'"), file)}

		response = post(url, files=files, auth=auth).json()["shortcode"]

	return response

def reply_reddit(submission, links):
	if len(links) == 1:
		mirror_text = "[Mirror](" + links[0] + ")  \n"
	elif links:
		mirror_format = "[Mirror [Part {}]]({})  \n"
		mirror_text = "".join(mirror_format.format(part, link) for part, link in enumerate(links, 1))

	reply_text = [
		mirror_text + "   \n^^I am a bot",
		"[Feedback](https://www.reddit.com/message/compose/?to=Gprime5&subject=PublicFreakout%20Mirror%20Bot)",
		"[Github](https://github.com/Gprime5/PublicFreakout-Mirror-Bot)"#,
		#"[Support me](https://www.paypal.me/gprime5)"
	]

	submission.reply(" | ".join(reply_text))

	save("Complete", ctime(), submission.permalink, ",".join(links))

def save(*values):
	with open("log.txt", "a") as file:
		text = "{},{},https://www.reddit.com{},{}"
		file.write(text.format(*values))

def cleanup():
	for file in listdir("Media"):
		if file != "ffmpeg.exe":
			remove("Media/" + i)

def upload(filename, title):
	url = "https://api.streamable.com/upload"

	with open("Media/" + filename, "rb") as file:
		files = {"file": (title.replace("’", "'"), file)}

		response = post(url, files=files, auth=auth).json()["shortcode"]

	return response

if __name__ == "__main__":
	main = PF()
	main.run()
