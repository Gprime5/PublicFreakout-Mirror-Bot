import ctypes
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
			self.hashes = [n for n in load(file) if n["created"] > time() - 2419200]

	def process(self, submission):
		if submission.is_self:
			yield ("Self post", ctime(), "")
			return

		check = bad_words.search(submission.title.lower())
		if check:
			yield ("'{}' in title".format(check.group()), ctime(), "")
			return

		try:
			info = self.yt.extract_info(submission.url, process=False)
		except DownloadError:
			info = {}
			pass

		if info.get("duration"):
			if info["duration"] < 1200:
				yield ("Downloading video", ctime(), "")
				self.yt.download([submission.url])
				h = sha256()
				with open("Media/output." + self.extension, "rb") as file:
					h.update(file.read())
				video_hash = h.hexdigest()

				for data in self.hashes:
					if data["video_url"] == submission.url or data["hash"] == video_hash:
						yield self._reply_reddit(submission, data["links"], data["reddit"])
						return
			else:
				yield ("Over 20 minutes", ctime(), "")
				return

		if submission.domain == "v.redd.it":
			for status in self._process_reddit(submission):
				yield i
			return

		response = self._streamable_import(submission)

		if response.status_code == 200: # OK
			code = response.json()["shortcode"]
			yield ("Streamable processing", ctime(), "")

			for status in self.wait_completed(code):
				yield (status, ctime(), "")

			if status == "Videos must be under 10 minutes":
				for i in self._process_multipart(submission, info):
					yield i
			elif "ERROR" in status:
				yield (status, ctime(), "")
			else: # Normal short video
				link = self._safe_url(code)
				yield ("Saving hash", ctime(), link)

				# If original video is not downloadable
				# then download streamable instread
				if info.get("duration") is None:
					self._download("output.mp4", link)
					self.extension = "mp4"

				self._save_hash(submission, "output." + self.extension, (link,))

				yield self._reply_reddit(submission, (link,))
		elif response.status_code == 403:
			raise Exception("Permission denied")
		elif response.status_code == 404:
			yield ("Video not found", ctime(), "")

	def run(self):
		while True:
			stream = reddit.subreddit("PublicFreakout").stream.submissions(pause_after=1)

			try:
				newest = next(reddit.user.me().comments.new(limit=1)).created_utc
			except RequestException:
				sleep(30)
				continue

			while True:
				try:
					# Get next post
					submission = next(stream)
				except RequestException:
					# Client side error
					sleep(30)
				except ServerError:
					sleep(30)
				except StopIteration:
					break
				else:
					if submission and submission.created_utc > newest:
						yield submission

	def save(self, submission, values):
		with open("log.txt", "a") as file:
			text = "https://redd.it/{} | {} | {} | {}\n"
			file.write(text.format(submission, *values))

	def wait_completed(self, code):
		""" Po;; video until 100% complete """

		url = "https://api.streamable.com/videos/"

		while True:
			response = get(url + code, auth=auth)

			if response.status_code == 200:
				response = response.json()

				for counter in range(6):
					if response["status"] == 0:
						text = "Uploading {}%" + " ." * counter
						yield text.format(response["percent"])
					elif response["status"] == 1:
						text = "Processing {}%" + " ." * counter
						yield text.format(response["percent"])
					elif response["status"] == 2:
						yield "Upload complete"
						return
					elif response["status"] == 3:
						yield response["message"]
						return

					sleep(1)
			else:
				yield response.text
				return

	def cleanup(self):
		for i in listdir("Media"):
			if i != "ffmpeg.exe":
				remove("Media/" + i)

	def _combine_media(self):
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

	def _download(self, filename, url):
		with open("Media/" + filename, "wb") as file:
			file.write(get(url).content)

	def _hook(self, status):
		self.extension = status["filename"].split(".")[-1]

	def _process_multipart(self, submission, info):
		""" Process videos between 10 and 20 minutes """

		parts = info["duration"] // 600 + 1

		for part in range(parts):
			command = [
				"Media/ffmpeg",
				"-v", "quiet",
				"-ss", str((info["duration"] * part) // parts),
				"-i", "Media/output." + self.extension,
				"-t", str((info["duration"] * (part + 1)) // parts),
				"-c", "copy",
				"Media/{}.{}".format(part, self.extension),
				"-y"
			]

			yield ("Creating part " + str(part + 1), ctime(), "")
			subprocess.run(command, creationflags=8)

		codes = []
		for part in range(parts):
			yield ("Uploading part " + str(part + 1), ctime(), "")
			filename = str(part) + "." + self.extension
			video_title = "{} [Part {}]".format(submission.title, part + 1)
			codes.append(self._upload(filename, video_title))

		for code in codes:
			for status in self.wait_completed(code):
				yield (status, ctime(), "")

		links = [self._safe_url(code) for code in codes]

		yield ("Saving hash", ctime(), "")
		self._save_hash(submission, "output." + self.extension, links)

		yield self._reply_reddit(submission, links)	

	def _process_reddit(self, submission):
		"""

		Download video or gif from v.redd.it domain
		then upload to streamable

		"""

		yield ("Downloading reddit video", ctime(), "")
		video_url = submission.media["reddit_video"]["fallback_url"]
		self._download("video", video_url)

		if submission.media["reddit_video"]["is_gif"]:
			yield ("Uploading gif", ctime(), "")
			code = self._upload("video", submission.title)
		else:
			yield ("Downloading reddit audio", ctime(), "")
			audio_url = video_url.rsplit("/", 1)[0] + "/audio"
			self._download("audio", audio_url)
			yield ("Combining media", ctime(), "")
			self._combine_media()
			yield ("Uploading video", ctime(), "")
			code = self._upload("output", submission.title)

		for status in self.wait_completed(code):
			yield (status, ctime(), "")

		link = self._safe_url(code)

		yield ("Saving hash", ctime(), link)
		self._save_hash(submission, "output", (link,))

		yield self._reply_reddit(submission, (link,))

	def _reply_reddit(self, submission, links, *extra_lines):
		if len(links) == 1:
			mirror_text = "[Mirror](" + links[0] + ")  \n"
		elif links:
			mirror_format = "[Mirror [Part {}]]({})  \n"
			mirror_text = "".join(mirror_format.format(part, link) for part, link in enumerate(links, 1))
		
		for line in extra_lines:
			mirror_text += line + "  \n"

		reply_text = [
			mirror_text + "   \n^^I am a bot",
			"[Feedback](https://www.reddit.com/message/compose/?to=Gprime5&subject=PublicFreakout%20Mirror%20Bot)",
			"[Github](https://github.com/Gprime5/PublicFreakout-Mirror-Bot)"#,
			#"[Support me](https://www.paypal.me/gprime5)"
		]

		submission.reply(" | ".join(reply_text))

		return ("Complete", ctime(), links[-1])

	def _safe_url(self, code):
		url = "https://ajax.streamable.com/videos/"
		link = "https:" + get(url + code, cookies=config["Streamable"]).json()["files"]["mp4"]["url"]

		return link

	def _save_hash(self, submission, filename, links):
		h = sha256()

		with open("Media/" + filename, "rb") as file:
			h.update(file.read())

		data = {
			"created": int(submission.created_utc),
			"reddit": submission.shortlink,
			"hash": h.hexdigest(),
			"video_url": submission.url,
			"links": links
		}

		self.hashes.append(data)

		with open("hashes.txt", "w") as file:
			dump(self.hashes, file, indent=4, sort_keys=True)

	def _streamable_import(self, submission):
		""" Import video from submission url to streamable """

		url = "https://api.streamable.com/import"

		parameters = {
			"url": submission.url,
			"title": submission.title
		}

		return get(url, parameters, auth=auth)

	def _upload(self, filename, title):
		url = "https://api.streamable.com/upload"

		with open("Media/" + filename, "rb") as file:
			files = {"file": (title.replace("’", "'"), file)}
			
			response = post(url, files=files, auth=auth).json()["shortcode"]

		return response

def error(e):
	if e:
		file = e.tb_frame.f_code.co_filename
		return [file, "\tLine: " + str(e.tb_lineno)] + error(e.tb_next)

	return []

if __name__ == "__main__":
	x = PF()

	try:
		for submission in x.run():
			for status in x.process(submission):
				pass

			x.save(submission, status)
			x.cleanup()
	except Exception as e:
		title = "Error: PublicFreakout.py ({})".format(getpid())
		errors = error(e.__traceback__)
		message = "\n".join([ctime(), "", *e.args, ""] + errors)
		ctypes.windll.user32.MessageBoxW(0, message, title, 0)
