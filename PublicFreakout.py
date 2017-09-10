import praw
from prawcore.exceptions import RequestException
from requests import get
from time import sleep, ctime
from configparser import ConfigParser

config = ConfigParser()
config.read("praw.ini")

reddit = praw.Reddit("Reddit")
PF = reddit.subreddit("PublicFreakout").stream.submissions()

# Skip old posts so only get new ones
for i in range(100):
	next(PF)

def make_streamable(post):
	"""

	Import video from submission to Streamable

	Return shortcode on success
	Return Error on failure

	"""

	url = "https://api.streamable.com/import"

	parameters = {
		"url": post.url,
		"title": post.title
	}

	auth = config["Streamable"]["username"], config["Streamable"]["password"]
	response = get(url, parameters, auth=auth)

	if response.status_code == 401: # Credential Error
		return {"Error": response.text}
	
	if response.status_code == 422: # Invalid URL
		return {"Error": response.json()["messages"]["url"][0]}

	return response.json()

def wait_completed(shortcode):
	url = "https://api.streamable.com/videos/"

	percent = get(url + shortcode).json()["percent"]

	while percent < 100:
		sleep(10)
		percent = get(url + shortcode).json()["percent"]

def post_to_reddit(post, shortcode):
	reply_text = [
		"[Streamable Mirror](https://streamable.com/{})\n\n^^I am a bot",
		"[Message author](https://www.reddit.com/message/compose/?to=Gprime5&subject=PublicFreakout%20Mirror%20Bot%20)",
		"[Github](https://github.com/Gprime5/PublicFreakout-Mirror-Bot)"
	]
	
	n = post.reply(" | ".join(reply_text).format(shortcode))

def log(text):
	with open("log.txt", "a") as file:
		file.write(text + "\n")

def run():
	while True:
		try:
			# Get next post
			post = next(PF)
		except RequestException:
			# If no connection, try again in 10 minutes
			log("Connection Error | " + ctime())
			sleep(10*60)
		else:
			# Skip self posts
			if post.is_self:
				continue

			response = make_streamable(post)

			if response.get("shortcode"):
				wait_completed(response["shortcode"])
				post_to_reddit(post, response["shortcode"])
			else:
				log("{} | {:<19} | {}".format(post.shortlink, response["Error"], ctime()))

if __name__ == "__main__":
	run()
