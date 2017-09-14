print("Initializing PublicFreakout.py")

import praw
from prawcore.exceptions import RequestException, ServerError
from requests import get, post
from time import sleep, ctime
from configparser import ConfigParser
import subprocess

config = ConfigParser()
config.read("praw.ini")

reddit = praw.Reddit("Reddit")
PF = reddit.subreddit("PublicFreakout").stream.submissions()
auth = config["Streamable"]["username"], config["Streamable"]["password"]

# Skip old posts so only get new ones
for i in range(100):
	next(PF)
print("Initialization Complete")

def import_streamable(submission):
	"""

	Import video from submission to Streamable

	Return shortcode on success
	Return Error on failure

	"""

	print("Importing streamable")

	url = "https://api.streamable.com/import"

	parameters = {
		"url": submission.url,
		"title": submission.title
	}

	return get(url, parameters, auth=auth)

def upload(filename, title):
	url = "https://api.streamable.com/upload"

	with open("Media\\" + filename + ".mp4", "rb") as file:
		files = {
			"file": file,
			"title": title
		}

		return post(url, files=files, auth=auth)

def download(name, url):
	print("Downloading " + name)

	with open("Media\\" + name + ".mp4", "wb") as file:
		file.write(get(url).content)

def combine_media():
	command = [
		'Media\\ffmpeg',
		'-i',
		'Media\\video.mp4',
		'-i',
		'Media\\audio.mp4',
		'-c',
		'copy',
		'Media\\output.mp4'
	]

	print("Combining video and audio")

	subprocess.run(command, creationflags=8)

def upload_streamable(submission):
	"""

	Download video and audio clip from reddit
	then upload to streamable

	"""

	print("Creating streamable")

	url = submission.media["reddit_video"]["fallback_url"]

	download("video", url)

	if submission.media["reddit_video"]["is_gif"]:
		return upload("video", submission.title)

	download("audio", url.rsplit("/", 1)[0] + "/audio")

	combine_media()

	return upload("output", submission.title)

def wait_completed(shortcode):
	"""

	Poll video until 100% complete

	"""

	url = "https://api.streamable.com/videos/"

	json = get(url + shortcode).json()

	while json["status"] != 2:
		if json["status"] == 3:
			return {"Error": json["message"]}

		sleep(1)

		json = get(url + shortcode).json()

	print("Streamable complete")

	return {"OK":""}

def post_to_reddit(submission, shortcode):
	print("https://streamable.com/" + shortcode)

	reply_text = [
		"[Mirror](https://streamable.com/" + shortcode + ")\n\n\n^^I am a bot",
		"[Message author](https://www.reddit.com/message/compose/?to=Gprime5&subject=PublicFreakout%20Mirror%20Bot%20)",
		"[Github](https://github.com/Gprime5/PublicFreakout-Mirror-Bot)"
	]

	try:
		submission.reply(" | ".join(reply_text))
	except praw.exceptions.APIException as e:
		print(e)

def log(reason, reddit="", streamable=""):
	with open("log.txt", "a") as file:
		file.write("{} | {} | {} | {}\n".format(reddit, reason, ctime(), streamable))

def run():
	while True:
		try:
			# Get next post
			submission = next(PF)
		except (RequestException, ServerError):
			# If no connection, try again in 10 minutes
			log("Connection Error")
			sleep(10*60)
		else:
			print("https://redd.it/" + str(submission))

			# Skip self posts
			if submission.is_self:
				continue

			if "sex" in submission.title.lower():
				continue
			if "fight" in submission.title.lower():
				continue

			if submission.domain == "v.redd.it":
				response = upload_streamable(submission)
			else:
				response = import_streamable(submission)

			if response.status_code == 200:
				json = response.json()

				wait = wait_completed(json["shortcode"])

				if wait.get("OK"):
					redd_response = post_to_reddit(submission, json["shortcode"])

					log("Success", submission.shortlink, "https://streamable.com/" + json["shortcode"])
				else:
					log(wait["Error"], submission.shortlink)
			else:
				if response.status_code == 401: # Credential Error
					log(response.text, submission.shortlink)
				elif response.status_code == 403: # Forbidden
					log("Forbidden", submission.shortlink)
					return
				elif response.status_code == 422: # Invalid URL
					log(response.json()["messages"]["url"][0], submission.shortlink)
				elif response.status_code == 429: # Too many requests
					log(response.text, submission.shortlink)
					return
				elif response.text.startswith("ERROR: "):
					log(response.text[7:], submission.shortlink)

if __name__ == "__main__":
	run()
