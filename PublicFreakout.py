import praw
import subprocess
import re
from prawcore.exceptions import RequestException, ServerError
from requests import get, post
from time import sleep, ctime, time
from configparser import ConfigParser
from youtube_dl import YoutubeDL
from youtube_dl.utils import DownloadError

config = ConfigParser()
config.read("praw.ini")

reddit = praw.Reddit(**config["Reddit"])
auth = config["Streamable"]["username"], config["Streamable"]["password"]
bad_words = re.compile("(?:sex|fight|naked|nude|brawl)")

def pprint(n):
    print(n, end=" | ", flush=True)

class PF():
    def __init__(self, log=None):
        self._log = log
        self.ext = "mp4"
        self.on = True

        self.yt = YoutubeDL({
            "quiet": True,
            "no_warnings": True,
            "outtmpl": "Media\\output.%(ext)s",
            "progress_hooks": [self.hook]
        })

    def log(self, txt):
        if self._log:
            self._log(txt)

    def start(self, n=0):
        self.log("Initializing")
        self.stream = reddit.subreddit("PublicFreakout").stream.submissions(pause_after=1)
        self.on = True

        for i in range(100 - n):
            next(self.stream)

        self.log("Initialized")

    def stop(self):
        self.on = False
        self.log("Ending")

    def run(self):
        while self.on:
            try:
                # Get next post
                submission = next(self.stream)
                self.log("Next submission: " + submission)
            except RequestException:
                # Client side error
                self.log("Connection error")
                self.on = False
            except ServerError:
                # Reddit server error
                self.log("Server error")
                sleep(10 * 60)
            else:
                if submission:
                    yield submission

            self.log("")
        else:
            self.log("Ended")

    def download(self, name, url):
        with open("Media\\" + name, "wb") as file:
            file.write(get(url).content)

    def upload(self, name, title):
        url = "https://api.streamable.com/upload"
        with open("Media\\" + name, "rb") as file:
            files = {"file": (title, file)}

            return post(url, files=files, auth=auth).json()["shortcode"]

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

        subprocess.run(command)

    def post_to_reddit(self, submission, codes):
        """Reply to submission with mirror(s)"""

        if len(codes) == 1:
            mirror_text = "[Mirror](https://streamable.com/"+codes[0]+")  \n"
        elif codes:
            mirror_format = "[Mirror[Part {}]](https://streamable.com/{})  \n"
            mirror_text = "".join(mirror_format.format(part, code) for part, code in enumerate(codes, 1))
        else:
            return ("Over 30 minutes", ctime())

        reply_list = " | ".join([
            mirror_text + "   \n^^I am a bot",
            "[Feedback](https://www.reddit.com/message/compose/?to=Gprime5&subject=PublicFreakout%20Mirror%20Bot)",
            "[Github](https://github.com/Gprime5/PublicFreakout-Mirror-Bot)"#,
            #"[Support me](https://www.paypal.me/gprime5)"
        ])

        submission.reply(reply_list)

        return ("Complete", ctime(), codes[-1])

    def streamable_import(self, submission):
        """Import video from submission to streamable"""

        url = "https://api.streamable.com/import"

        parameters = {
            "url": submission.url,
            "title": submission.title
        }

        return get(url, parameters, auth=auth)

    def wait_completed(self, shortcode):
        """Poll video until 100% complete"""

        url = "https://api.streamable.com/videos/"
        
        while True:
            response = get(url + shortcode, auth=auth)

            if "ERROR" in response.text:
                yield (response.text, ctime())
                return

            try:
                response = response.json()
            except:
                print(response.status_code)
                print(response.text)

            for counter in range(6):
                if response["status"] == 0:
                    yield ("Uploading" + " ." * counter, ctime())
                elif response["status"] == 1:
                    yield ("Processing" + " ." * counter, ctime())
                elif response["status"] == 2:
                    yield ("Upload complete", ctime())
                    return
                elif response["status"] == 3:
                    yield (response["message"], ctime())
                    return

                sleep(1)

    def process(self, submission):
        if submission.is_self:
            return ("Self post", ctime(), "")

        check = bad_words.search(submission.title.lower())
        if check:
            return ("'{}' in title".format(check.group()), ctime(), "")

        if submission.domain == "v.redd.it":
            return ("Reddit submission", ctime(), "")

        response = self.streamable_import(submission)

        if response.status_code == 200: # OK
            return ("Streamable processing", ctime(), response.json()["shortcode"])
        if response.status_code == 403: # Permission denied
            return ("Permission denied", ctime(), "")
        if response.status_code == 404:
            return ("Video not found", ctime(), "")

    def hook(self, status):
        self.ext = status["filename"].split(".")[-1]

    def import_parts(self, url):
        info = self.yt.extract_info(url, process=False)

        if info["duration"] < 1800:
            self.yt.download([url])
        else:
            return ("Over 30 minutes", ctime())

        parts = info["duration"] // 600 + 1

        for part in range(parts):
            command = [
                "Media\\ffmpeg",
                "-v", "quiet",
                "-ss", str((info["duration"]*part)//parts),
                "-i", "Media\\output." + self.ext,
                "-t", str((info["duration"]*(part+1))//parts),
                "-c", "copy",
                "Media\\{}.{}".format(part, self.ext),
                "-y"
            ]

            subprocess.run(command)

            yield (part, ctime())
