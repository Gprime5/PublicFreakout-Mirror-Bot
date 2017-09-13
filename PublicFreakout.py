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

	Return request response object

	"""

	print("Importing streamable")

	url = "https://api.streamable.com/import"

	parameters = {
		"url": submission.url,
		"title": submission.title
	}
	
	return get(url, parameters, auth=auth)

def upload(filename, title):
	"""
	
	Uploads file to streamable
	Return request response object
	
	"""
	
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

	subprocess.run(command, creationflags=8)

def upload_streamable(submission):
	"""

	Download video and audio clip from reddit
	combine them into a single video
	then upload to streamable
	
	Return request response object

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
	
	Return True on complete
	Return None on Error

	"""

	url = "https://api.streamable.com/videos/"

	response = get(url + shortcode).json()

	if response["message"] == "Videos must be under 10 minutes":
		return
	if response["message"] == "Could not process file":
		return

	json = get(url + shortcode).json()

	while json["percent"] < 100:
		if json["status"] != 1:
			return

		sleep(1)

		json = get(url + shortcode).json()

	print("Streamable complete")

	return True

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

def log(text):
	with open("log.txt", "a") as file:
		file.write(text + "\n")

def run():
	try:
		# Get next post
		submission = next(PF)
	except (RequestException, ServerError):
		# If no connection, try again in 10 minutes
		log("Connection Error | " + ctime())
		sleep(10*60)
	else:
		print("https://redd.it/" + str(submission))

		# Skip self posts
		if submission.is_self:
			return

		if submission.domain == "v.redd.it":
			response = upload_streamable(submission)
		else:
			response = import_streamable(submission)

		if response.status_code == 200: # Response OK
			json = response.json()

			if wait_completed(json["shortcode"]):
				redd_response = post_to_reddit(submission, json["shortcode"])

				log("{} | Success | {} | https://streamable.com/{}".format(submission.shortlink, ctime(), json["shortcode"]))
			else:
				log("{} | Error | {} | ".format(submission.shortlink, ctime()))
		else:
			if response.status_code == 401: # Credential Error
				log("{} | {} | {} | ".format(submission.shortlink, response.text, ctime()))
			elif response.status_code == 422: # Invalid URL
				log("{} | {} | {} | ".format(submission.shortlink, response.json()["messages"]["url"][0], ctime()))
			elif response.text.startswith("ERROR: "):
				log("{} | {} | {} | ".format(submission.shortlink, response.text[7:], ctime()))

if __name__ == "__main__":
	while True:
		run()
