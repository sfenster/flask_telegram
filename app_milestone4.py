# THIS PROGRAM NEEDS FFMPEG INSTALLED THROUGH APT TO RUN CORRECTLY


import os
import string
import subprocess
import asyncio
import importlib
import sqlite3
import dotenv
import requests
import yt_dlp
import logging
from bs4 import BeautifulSoup
from mega import Mega
from quart import Quart, Response
from telethon import TelegramClient, events, errors
from telethon.tl.types import DocumentAttributeVideo

dotenv.load_dotenv()
api_id = os.environ.get('API_ID')
api_hash = os.environ.get('API_HASH')
mega_email = os.environ.get('MEGA_EMAIL')
mega_password = os.environ.get('MEGA_PASSWORD')
mega = Mega()
mega_login = mega.login(mega_email, mega_password)
session_name = 'flask_api_session'

app = Quart(__name__)

client = TelegramClient(session=session_name, api_id=api_id, api_hash=api_hash)
channels_queue = []
task = None
video_min_duration = 10
downloads = None
home = os.path.expanduser('~')

prev_messages_limit = 5
single_chat_id = -1001529959609
single_chat_msg_limit = None
channel_list = []

app_routes = {
    "/channels": "Lists all channels",
    "/start": "Starts polling for new messages",
    "/stop": "Stops polling for new messages",
    "/add/": "Adds a new channel to polling list",
    "/delete/": "Deletes an existing channe from polling list"
}

# Get the environment object for config.py using the 'APP_SETTINGS' env variable
envclass_name, envsubclass_name = os.environ.get(
    "APP_SETTINGS", 'config.DevelopmentConfig').split(".")
envclass = importlib.import_module(envclass_name)
env = getattr(envclass, envsubclass_name)


def get_download_dir():
    dl = getattr(env, 'DOWNLOADS')
    dl = dl.replace("~", home)
    try:
        if os.access(dl, os.W_OK):
            return dl  # File was opened successfully
        # Default to home directory if specified path is not accessible
        else:
            dl = f'{home}/incoming'
            return dl
    except OSError as e:
        # File location is not accessible or writable
        print(f'Error: {str(e)}')


def create_downloads_table(conn):
    cursor = conn.cursor()
    cursor.execute(
        'CREATE TABLE IF NOT EXISTS downloaded_videos (id INTEGER PRIMARY KEY)')


def check_already_downloaded(conn, video_id):
    try:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id FROM downloaded_videos WHERE id=?', (video_id,))
        return cursor.fetchone() is not None
    except Exception as e:
        print(f'Error: {str(e)}')


def add_to_downloaded(conn, video_id):
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO downloaded_videos (id) VALUES (?)', (video_id,))
    conn.commit()


def get_file_path(chat_title, message):

    file_name = f'{message.message.replace(" ", "_")}.mp4' if message.message else f'{message.id}.mp4'
    print(f'Potential file path = {downloads}/{chat_title}/{file_name}')
    return f'{downloads}/{chat_title}/{file_name}'


async def post_video_to_channel(client, video_file, caption=''):
    chat_id=-1001502645812
    try:
        # Find the channel entity
        channel = await client.get_entity(chat_id)

        # Get the absolute path of the video file
        abs_video_file = os.path.abspath(video_file)

        # Extract video metadata using ffprobe
        ffprobe_cmd = [
            'ffprobe',
            '-v',
            'error',
            '-select_streams',
            'v:0',
            '-show_entries',
            'stream=width,height,duration',
            '-of',
            'default=noprint_wrappers=1:nokey=1',
            abs_video_file
        ]
        output = subprocess.check_output(
            ffprobe_cmd).decode('utf-8').strip().split('\n')
        width, height = map(int, output[:-1])
        duration = round(float(output[-1]))

        # Upload the video file
        video = await client.upload_file(video_file)

        # Create a document attribute for the video
        video_attr = DocumentAttributeVideo(
            w=width,
            h=height,
            duration=int(duration)
        )

        # Post the video to the channel
        # await client.send_file(channel, video, caption=caption)

        await client.send_file(
            channel,
            video,
            caption=caption,
            attributes=[video_attr]
        )

        print("Video posted successfully!")
    except errors.FloodWaitError as e:
        print(
            f"Telegram API flood limit exceeded. Retry after {e.seconds} seconds.")
    except errors.ChatWriteForbiddenError:
        print("You don't have permission to post in this channel.")
    except errors.SlowModeWaitError as e:
        print(f"Slow mode is enabled. Retry after {e.seconds} seconds.")
    except errors.RPCError as e:
        print(f"Error occurred while posting the video: {e}")

async def download_video(client, message, file_path):
    # Download the video and track the download progress
    try:
        # Get the duration of the video
        duration = message.file.duration

        # Only download the video if it's longer than 10 seconds
        if duration > video_min_duration:
            video_file = await client.download_media(message, file=file_path, progress_callback=lambda d, t: print(f'{d}/{t} bytes downloaded ({d/t*100:.2f}%)'))
            print(f'Video saved to {file_path}')
            
            # Add the video ID to the downloaded_videos table
            with sqlite3.connect('downloads.db') as conn:
                create_downloads_table(conn)
                add_to_downloaded(conn, message.video.id)
            
            # Upload the video file to Mega.nz
            try:
                if mega_email and mega_password:
                    mega_folder = mega_login.find('Telegram Videos')
                    if not mega_folder:
                        mega_folder = mega_login.create_folder('Telegram Videos')
                    print(f'Uploading {message.video.id} to Mega.')
                    mega_file = mega_login.upload(
                        video_file, mega_folder[0])
                print(
                    f"Uploaded video {message.video.id} to Mega.nz file '{mega_file['name']}' in folder '{mega_folder[0]['astring']}'")
            except Exception as e:
                print(
                    f'Error uploading video {message.video.id} to Mega.nz: {e}')
            # Delete the local video file
            os.remove(video_file)
        else:
            print(
                f'Video duration is {duration}s, which is shorter than {video_min_duration}s. Skipping download.')
    except Exception as e:
        print(f'Error downloading video {message.video.id}: {e}')




async def get_dialogs():
    async for dialog in client.iter_dialogs():
        channels_queue.append({'id': dialog.id, 'title': dialog.title})


async def handle_video(event):
    print('New message detected.')
    message = event.message
    chat = await event.get_chat()
    chat_title = chat.title.replace(' ', '_')
    print(
        f'New message from chat {chat_title} — id: {message.id}, text: {message.message}')

    # Check if the message contains a video
    if message.video:
        print(f'New message contains video called {message.video.id}.')
        # Define the file path where the video will be saved
        file_path = get_file_path(chat_title, message)
        # Create the folder if it doesn't exist
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Check if the video has already been downloaded
        with sqlite3.connect('downloads.db') as conn:
            create_downloads_table(conn)
            already_downloaded = check_already_downloaded(
                conn, message.video.id)

        if already_downloaded:
            print(
                f'Video with ID {message.video.id} has already been downloaded.')
        else:
            # Download the video
            await download_video(client, message, file_path)


async def handle_previous_videos(chat, prev_messages_limit=None):
    chat_title = chat.title.replace(' ', '_')
    async for message in client.iter_messages(chat, limit=prev_messages_limit):
        try:
            if message.video:
                print(
                    f'Message has video with id {message.video.id} and duration {message.file.duration}.')
                file_path = get_file_path(chat_title, message)
                with sqlite3.connect('downloads.db') as conn:
                    already_downloaded = check_already_downloaded(
                        conn, message.video.id)

                if not already_downloaded:
                    await download_video(client, message, file_path)
                else:
                    print(f'{message.video.id} already downloaded.')
        except Exception as e:
            print(f'Error: {str(e)}')
            print('Resuming...')


async def import_channels_from_file(file_path):
    global channel_list
    try:
        with open(file_path, 'r') as f:
            channels = f.readlines()
            print("CHANNELS:")
            for channel in channels:
                # Remove any whitespace characters from the start and end of the line
                channel_id = int(channel.strip())
                channel_list.append(channel_id)
                print(f'{channel_id}')
    except FileNotFoundError:
        print(f"Error: could not find channel file at {file_path}")


def download_progress_hook(d):
    if d['status'] == 'downloading':
        downloaded = d['downloaded_bytes']
        #total = d['total_bytes']
        eta = d['eta']
        print(f"Downloaded {downloaded} bytes - {eta} seconds left.")
    elif d['status'] == 'finished':
        print("Download completed!")


@app.before_serving
async def startup():
    global downloads
    downloads = get_download_dir()
    print(f'download directory: {downloads}')
    await client.start()
    await import_channels_from_file('./channels.txt')


@app.after_serving
async def teardown():
    global task
    if task is not None and not task.done():
        task.cancel()
    client.disconnect()


@app.route("/")
async def index():
    available_routes = []
    output = ""
    for route, description in app_routes.items():
        output += f"{route}: {description}\n"
    return "<pre>" + output + "</pre>"


@app.route("/channels")
async def channels():
    await get_dialogs()
    output_str = ""
    for channel in channels_queue:
        output_str += f"id: {channel['id']}, title: {channel['title']}\n"
    return Response(output_str, mimetype="text/plain")


@app.route("/start")
async def start_polling():
    global task
    if task is None or task.done():
        client.add_event_handler(
            handle_video, events.NewMessage(chats=channel_list))
        task = asyncio.create_task(client.run_until_disconnected())
        return "Polling started"
    else:
        return "Polling already running"


@app.route("/stop")
async def stop_polling():
    global task
    if task is not None and not task.done():
        client.remove_event_handler(
            handle_video, events.NewMessage(chats=channel_list))
        task.cancel()
        return "Polling stopped"
    else:
        return "Polling not running"


@app.route("/add/<channel_id>", methods=["POST"])
async def add_channel(channel_id):
    global channel_list
    try:
        channel_id = int(channel_id)
    except ValueError:
        return Response("Invalid channel ID provided.", status=400)
    try:
        channel = await client.get_entity(channel_id)
        if channel_id not in channel_list:
            channel_list.append(channel_id)
            with open("channels.txt", "a") as file:
                file.write(f"{channel_id}\n")
            return Response(f"Added channel {channel_id} to list and file.", mimetype="text/plain")
        else:
            return Response(f"Channel {channel_id} already exists in list and file.", mimetype="text/plain")
    except Exception as e:
        return f"Error: {channel_id} is not a valid Telegram channel ID. {e}"


@app.route("/delete/<channel_id>", methods=["POST"])
async def delete_channel(channel_id):
    global channel_list
    channel_id = int(channel_id)
    if channel_id in channel_list:
        channel_list.remove(channel_id)
        with open("channels.txt", "r+") as file:
            lines = file.readlines()
            file.seek(0)
            for line in lines:
                if line.strip() != str(channel_id):
                    file.write(line)
            file.truncate()
        return Response(f"Deleted channel {channel_id} from list and file.", mimetype="text/plain")
    else:
        return Response(f"Channel {channel_id} does not exist in list and file.", mimetype="text/plain")


@app.route("/rip/<id>/<limit>")
async def rip_channel(id, limit=single_chat_msg_limit):
        # Call the handle_previous_videos() function for a single chat
    try:
        if id is not None:
            chat = await client.get_entity(int(id))
            await handle_previous_videos(chat, int(limit))
            return Response(status=200)
    except Exception as e:
        return f"Error: id absent or not valid. Format: /rip/[id]/[limit]> \n This is the id we found in the URL: {id}. \n{e}"

@app.route("/recent")
async def recent_vids_from_all_channels():
    if prev_messages_limit is not None:
        for chat_id in channel_list:
            chat = await client.get_entity(chat_id)
            await handle_previous_videos(chat, prev_messages_limit)


@app.route("/scrape/<path>")
async def scrape_page(path):
    file_path = f'{downloads}/xhamster/'
    resp=""
    web_url = 'https://www.xhamster.com/videos/' + path
    print(f'Web URL: {web_url}')
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.93 Safari/537.36'}
    print(f'URL = {web_url}')
    # Get URL Content
    r = requests.get(web_url)

    # Parse HTML Code
    soup = BeautifulSoup(r.content, 'html.parser')

    # List of all video tag
    video_tags = soup.findAll('video')
    print("Total ", len(video_tags), "videos found")

    if len(video_tags) != 0:
        for video_tag in video_tags:
            video_url = video_tag['src']
            resp = resp + video_url + '\n'
    else:
        resp = "no videos found"

    video_url = "https://www.youtube.com/watch?v=fAixjMvyNX0"
    logger = logging.getLogger('youtube-dl')
    logger.addHandler(logging.StreamHandler())
    file_type = 'mp4'

    ydl_opts = {
        'logger': logger,
        'outtmpl': f'{file_path}%(title)s.%(ext)s',
        'format': 'bestvideo[ext={0}]+bestaudio[ext={0}]/best'.format(file_type),
        'merge_output_format': 'mp4',
        'progress_hooks': [download_progress_hook],
        'prefer_ffmpeg': True,
        'restrictfilenames': True,
        'verbose': True,
        'recode-video': 'mp4',
    }


    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info_dict = ydl.extract_info(web_url, download=False)
            video_title = info_dict.get('title', 'video').replace(" ", "_")
            video_title = "".join(
                char for char in video_title if char not in string.punctuation or char == "_")
            print(f'Attempting to download {web_url} to {file_path}{video_title}.{file_type}')
            ydl.download([web_url])
            print(f'Successfully downloaded "{video_title}.{file_type}" to {file_path}')
            upload_file = file_path + video_title + '.' + file_type     
        except Exception as e:
            print(f'Failed to download the video: {str(e)}')
        try:
            print('Attempting to upload to Telegram.')
            await post_video_to_channel(client, upload_file, video_title)
        except Exception as e:
            print(f'Failed to upload the video: {str(e)}')
        

    return Response(resp, status=200)


# Preserve the ability to run in dev with a simple 'python app.py' command to start dev server
if __name__ == "__main__":
    app.run(loop=client.loop)
