import praw
import subprocess
import re
from functools import partial
from prawcore.exceptions import RequestException, ServerError
from requests import get, post
from time import sleep, ctime
from configparser import ConfigParser
from youtube_dl import YoutubeDL
from youtube_dl.utils import DownloadError

pprint = partial(print, end=" | ", flush=True)
pprint("Initializing PublicFreakout.py")

config = ConfigParser()
config.read("praw.ini")

reddit = praw.Reddit("Reddit")
auth = config["Streamable"]["username"], config["Streamable"]["password"]
bad_words = re.compile("(?:sex|fight|naked|nude|brawl)")
yt = YoutubeDL({"quiet":True, "no_warnings":True, "outtmpl":"Media\\output.mp4"})

print("Complete")

def download(name, url):
	pprint("Downloading " + name)

	with open("Media\\" + name + ".mp4", "wb") as file:
		file.write(get(url).content)

def upload(name, title):
	url = "https://api.streamable.com/upload"

	with open("Media\\" + name + ".mp4", "rb") as file:
		files = {"file": (title, file)}

		return post(url, files=files, auth=auth)

def combine_media():
	command = [
		"Media\\ffmpeg",
		"-i", "Media\\video.mp4",
		"-i", "Media\\audio.mp4",
		"-c", "copy",
		"Media\\output.mp4",
		"-y"
	]

	pprint("Combining video and audio")

	subprocess.run(command, creationgflags=8)

def wait_completed(shortcode):
	"""

	Poll video until 100% complete

	"""

	url = "https://api.streamable.com/videos/"

	response = get(url + shortcode, auth=auth)

	try:
		json = response.json()
	except:
		print("Wait error")
		return {"Error": response.text}

	while json["status"] != 2:
		if json["status"] == 3:
			return {"Error": json["message"]}

		sleep(1)

		response = get(url + shortcode, auth=auth)

		try:
			json = response.json()
		except:
			print("Wait error")
			return {"Error": response.text}

	pprint("Streamable complete")

	return {"OK": True}

def import_from_reddit(submission):
	"""

	Download video and audio clip from reddit
	then upload to streamable

	"""


	pprint("Transferring from reddit")

	url = submission.media["reddit_video"]["fallback_url"]

	download("video", url)

	if submission.media["reddit_video"]["is_gif"]:
		return upload("video", submission.title)

	download("audio", url.rsplit("/", 1)[0] + "/audio")

	combine_media()

	return upload("output", submission.title)

def import_from_other(submission):
	"""

	Import video from submission to Streamable

	"""

	pprint("Importing streamable")

	url = "https://api.streamable.com/import"

	parameters = {
		"url": submission.url,
		"title": submission.title
	}

	return get(url, parameters, auth=auth)

def post_to_reddit(submission, shortcodes):
	print("https://streamable.com/" + shortcodes[-1], ctime())

	if len(shortcodes) == 1:
		reply_text = [
			"[Mirror](https://streamable.com/" + shortcodes[0] + ")  \n   \n^^I am a bot",
			"[Feedback](https://www.reddit.com/message/compose/?to=Gprime5&subject=PublicFreakout%20Mirror%20Bot)",
			"[Github](https://github.com/Gprime5/PublicFreakout-Mirror-Bot)",
			"[Support me](https://www.paypal.me/gprime5)"
		]
	else:
		reply_format = "[Mirror [Part {}]](https://streamable.com/{})  \n"
		reply_text = [reply_format.format(part, code) for part, code in enumerate(shortcodes, 1)]
		reply_text = [
			"".join(reply_text) + "   \n^^I am a bot",
			"[Feedback](https://www.reddit.com/message/compose/?to=Gprime5&subject=PublicFreakout%20Mirror%20Bot)",
			"[Github](https://github.com/Gprime5/PublicFreakout-Mirror-Bot)",
			"[Support me](https://www.paypal.me/gprime5)"
		]

	submission.reply(" | ".join(reply_text))

def import_parts(url):
	info = yt.extract_info(url, False, process=False)

	if not (600 < info["duration"] < 1800):
		return

	yt.download([url])

	start, end = 0, 0
	parts = info["duration"] // 600 + 1
	uploaded = []

	for part in range(parts):
		part_duration = info["duration"] // (parts - part)
		end += part_duration

		command = [
			"Media\\ffmpeg", "-v", "quiet", "-y", "-ss",
			"{:0>2}:{:0>2}".format(start//60, start%60),
			"-i", "Media\\output.mp4", "-to",
			"{:0>2}:{:0>2}".format(end//60, end%60),
			"-c", "copy", "Media\\output{}.mp4".format(part)
		]

		subprocess.run(command)

		info["duration"] -= part_duration
		start = end
		title = "{} [Part {}]".format(info["title"], part + 1)

		pprint("Uploading " + str(part))
		uploaded.append(upload("output" + str(part), title))

	return uploaded

def check_parts(submission, response):
	codes = [n.json()["shortcode"] for n in response]
	for code in codes:
		wait_completed(code)

	reddit_response = post_to_reddit(submission, codes)

def check_response(submission, response):
	if response.status_code == 200: # OK
		json = response.json()

		wait = wait_completed(json["shortcode"])

		if wait.get("OK"):
			reddit_response = post_to_reddit(submission, (json["shortcode"],))

			log("Success", submission.shortlink, "https://streamable.com/" + json["shortcode"])
		elif wait["Error"] == "Videos must be under 10 minutes":
			response = import_parts(submission.url)

			if response:
				check_parts(submission, response)
			else:
				print("Video over 30 minutes")
				log("Video over 30 minutes", submission.shortlink)
		else:
			print("Wait error: " + wait["Error"])
			log("Wait error: " + wait["Error"], submission.shortlink)
	else:
		print("Streamable error: " + str(response.status_code))

		if response.status_code == 422: # Invalid URL
			log(response.json()["messages"]["url"][0], submission.shortlink)
		elif response.text.startswith("ERROR: "):
			log(response.text, submission.shortlink)
		else:
			log(str(response.status_code) + " - " + response.text, submission.shortlink)

def process(submission):
	pprint("https://redd.it/" + submission.id)

	if submission.is_self:
		return

	check = bad_words.search(submission.title.lower())
	if check:
		output = "'{}' in title".format(check.group())
		log(output, submission.shortlink)
		print(output)

		return

	if submission.domain == "v.redd.it":
		response = import_from_reddit(submission)
	else:
		response = import_from_other(submission)

	check_response(submission, response)

def log(reason, reddit="", streamable=""):
	with open("log.txt", "a") as file:
		info = reddit, reason, ctime(), streamable
		file.write("{} | {} | {} | {}\n".format(*info))

def run(stream):
	while True:
		try:
			# Get next post
			submission = next(stream)
		except RequestException:
			# Client side connection error
			log("Connection Error")
			return
		except ServerError:
			# Reddit server errpr
			log("Server Error")
			sleep(10 * 60)
		else:
			process(submission)

if __name__ == "__main__":
	stream = reddit.subreddit("PublicFreakout").stream.submissions()

	for i in range(100):
		next(stream)

	run(stream)

	sleep(10 * 60)

	while True:
		stream = reddit.subreddit("PublicFreakout").stream.submissions()

		for i in range(100):
			next(stream)

		run(stream)

		sleep(10 * 60)
