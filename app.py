# THIS PROGRAM NEEDS FFMPEG INSTALLED THROUGH APT TO RUN CORRECTLY
# In order to use flask extensions like Flask-WTF, 'import quart.flask_patch' must be the first import
import quart.flask_patch

import os
import string
import subprocess
import asyncio
import importlib
import sqlite3
import requests
import yt_dlp
import logging
from bs4 import BeautifulSoup
from mega import Mega
from quart import Quart, Response, render_template, request, jsonify, copy_current_request_context
from flask_wtf import FlaskForm
from wtforms import Form, StringField, BooleanField, TextAreaField, SubmitField, HiddenField, validators
from telethon import TelegramClient, events, errors
from telethon.tl.types import DocumentAttributeVideo, Channel, ChannelParticipantAdmin, ChannelParticipantCreator
from config import CONFIG, get_secret_key, get_environ_class

mega = Mega()
mega_login = mega.login(CONFIG.mega.MEGA_EMIAL, CONFIG.mega.MEGA_PASSWORD)

app = Quart(__name__)

client = TelegramClient(session=CONFIG.login.SESSION_NAME,
                        api_id=CONFIG.login.API_ID, api_hash=CONFIG.login.API_HASH)
channels_queue = []
task = None
video_min_duration = 10
downloads = None
home = os.path.expanduser('~')

prev_messages_limit = 5
single_chat_id = -1001529959609
single_chat_msg_limit = None
channel_list = []
stop_download_flag = False
stop_event = asyncio.Event()  # Define the module-level event object

# Global lists to store the channels and groups
all_channels_and_groups = []
owned_channels_and_groups = []
postable_channels_and_groups = []

app_routes = {
    "/channels": "Lists all channels",
    "/start": "Starts polling for new messages",
    "/stop": "Stops polling for new messages",
    "/add/": "Adds a new channel to polling list",
    "/delete/": "Deletes an existing channe from polling list",
    "/scrape": "Downloads all videos embedded in a URL"
}

env = get_environ_class()
app.config['SECRET_KEY'] = CONFIG.secret_key


class MyForm(FlaskForm):
    name = StringField('name', validators=[validators.DataRequired()])

class VideoDownloadForm(FlaskForm):
    url = StringField('URL', validators=[validators.DataRequired()])
    upload_to_telegram = BooleanField('Upload to Telegram')
    retain_file = BooleanField('Retain File')
    console_output = TextAreaField(
        'Console Output', render_kw={'readonly': True})
    stop_download_button = BooleanField('Stop Downloads')
    stop_download_flag = HiddenField()

async def populate_channel_lists():
    global all_channels_and_groups, owned_channels_and_groups, postable_channels_and_groups
    
    # Retrieve all dialogs (channels and chats)
    async for dialog in client.iter_dialogs():
        #if isinstance(dialog.entity, Channel):
        output_str = ""
        megagroup = False
        forum = False
        creator = None
        try:
            entity = dialog.entity
            if dialog.is_channel:
                # Add the channel or group to the all_channels_and_groups list
                all_channels_and_groups.append(dialog.entity)
                megagroup = entity.megagroup
                forum = entity.forum
                creator = entity.creator
            # Check if you are an administrator in the channel or group
            if creator == True:
                # You own the channel or group
                owned_channels_and_groups.append(dialog.entity)
            if dialog.is_group:
                # You have posting rights in the channel or group
                postable_channels_and_groups.append(dialog.entity)
        except errors.ChatAdminRequiredError as e:
            # Handle chat admin required errors, if necessary
            print(f"Admin required: {e}")
        except errors.RPCError as e:
            # Handle other RPC errors, if necessary
            print(f"RPC error: {e}")




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


async def post_video_to_channel(client, video_file, chat_id, caption=''):
    global console_output
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
        console_output.append('Attempting to upload to Telegram.')
        video = await client.upload_file(video_file)
        console_output.append('Video uploaded successfully!')
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
        console_output.append(
            f'Failed to upload the video: {str(e)}')
    except errors.ChatWriteForbiddenError:
        print("You don't have permission to post in this channel.")
        console_output.append(
            f'Failed to upload the video: {str(e)}')
    except errors.SlowModeWaitError as e:
        print(f"Slow mode is enabled. Retry after {e.seconds} seconds.")
        console_output.append(
            f'Failed to upload the video: {str(e)}')
    except errors.RPCError as e:
        print(f"Error occurred while posting the video: {e}")
        console_output.append(
            f'Failed to upload the video: {str(e)}')
        
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


async def scrape_playlist(entries, ydl, file_path, file_type, upload_to_telegram, retain_file, console_output, form):
    for entry in entries:
        if form.stop_download_button.data:
            # Handle interrupt here if interrupt flag is True
            break  # Exit the loop and go to the return statement
        video_url = entry.get('webpage_url')
        if video_url:
            entry_dict = ydl.extract_info(
                video_url, download=False)
            video_title = entry_dict.get(
                'title', 'video').replace(" ", "_")
            video_title = "".join(
                char for char in video_title if char not in string.punctuation or char == "_")
            full_file_path = file_path + video_title + '.' + file_type
            if not os.path.exists(full_file_path):
                console_output.append(
                    f'Downloading video: {video_url}')
                ydl.download([video_url])
                console_output.append(
                    f'Successfully downloaded video: {video_url}')

                if upload_to_telegram:
                    chat_id = -1001502645812
                    await post_video_to_channel(client, full_file_path, chat_id, video_title)
                if not retain_file:
                    os.remove(full_file_path)
                    console_output.append(
                        'File deleted.')
            else:
                console_output.append(
                    f'{full_file_path} already exists. Skipping.')
        else:
            console_output.append(
                'No video URL found in playlist entry.')


@app.before_serving
async def startup():
    global downloads
    downloads = get_download_dir()
    print(f'download directory: {downloads}')
    await client.start()
    await import_channels_from_file('./channels.txt')
    await populate_channel_lists()


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
    # await get_dialogs()
    output_str = ""
    megagroup = False
    forum = False
    creator=None
    async for dialog in client.iter_dialogs():
        try:
            entity = dialog.entity
            if dialog.is_channel:
                megagroup=entity.megagroup
                forum=entity.forum
                creator=entity.creator
            output_str += f"{dialog.title} - id: {dialog.id} \n\
    creator: {creator}\n\
    is_group: {dialog.is_group}, is_channel: {dialog.is_channel} \n\
    megagroup: {megagroup}, forum: {forum}\n"
        except errors.RPCError as e:
            print(f"RPC error: {e}")
        
    #for channel in channels_queue:
    #    output_str += f"id: {channel['id']}, title: {channel['title']}\n"
    return Response(output_str, mimetype="text/plain")

    

    #return await render_template('channels.html',
    #                            all_channels=all_channels_and_groups,
    #                            owned_channels=owned_channels_and_groups,
    #                            postable_channels=postable_channels_and_groups)


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

@app.route('/scrape', methods=['GET', 'POST'])
async def scrape_page():
    global stop_download_flag
    if request.method == 'POST':
        form = VideoDownloadForm(await request.form, meta={'csrf': False})

        # Check if the interrupt button is clicked
        if form.stop_download_button.data:
            # Set the interrupt flag in the form to True
            stop_event.set()
            form.validate()  # Trigger form validation to update the flag value
            # Handle the interrupt gracefully
            return jsonify({'message': 'Downloads stopped successfully'})

        if form.validate_on_submit():
            # Set the flag to True after the form is submitted
            show_stop_downloads = True
            stop_download_flag = False
            url = form.url.data.strip()
            upload_to_telegram = form.upload_to_telegram.data
            retain_file = form.retain_file.data

            file_path = f'{downloads}/xhamster/'
            web_url = url
            console_output = []
            file_type = 'mp4'

            ydl_opts = {
                'outtmpl': f'{file_path}%(title)s.%(ext)s',
                'format': 'bestvideo[ext={0}]+bestaudio[ext={0}]/best'.format(file_type),
                'merge_output_format': 'mp4',
                'progress_hooks': [download_progress_hook],
                'prefer_ffmpeg': True,
                'restrictfilenames': True,
                'verbose': True,
                'recode-video': 'mp4',
                'yes-playlist': True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    info_dict = ydl.extract_info(web_url, download=False)
                    if '_type' in info_dict and info_dict['_type'] == 'playlist':
                        entries = info_dict.get('entries')
                        if entries:
                            asyncio.ensure_future(scrape_playlist(
                                entries, ydl, file_path, file_type, upload_to_telegram, retain_file, console_output, form))
                    else:
                        video_title = info_dict.get(
                            'title', 'video').replace(" ", "_")
                        video_title = "".join(
                            char for char in video_title if char not in string.punctuation or char == "_")
                        full_file_path = file_path + video_title + '.' + file_type
                        if not os.path.exists(full_file_path):
                            console_output.append(
                                f'Attempting to download {web_url} to {full_file_path}')
                            ydl.download([web_url])
                            console_output.append(
                                f'Successfully downloaded "{video_title}.{file_type}" to {full_file_path}')

                            if upload_to_telegram:
                                chat_id = -1001502645812
                                await post_video_to_channel(client, full_file_path, chat_id, video_title)
                            if not retain_file:
                                os.remove(full_file_path)
                                console_output.append('File deleted.')
                        else:
                            console_output.append(
                                f'{full_file_path} already exists. Skipping.')
                except Exception as e:
                    console_output.append(
                        f'Failed to download the video: {str(e)}')

            form.console_output.data = '\n'.join(console_output)

    else:
        show_stop_downloads = False
        form = VideoDownloadForm(show_stop_downloads=show_stop_downloads)
        #form = VideoDownloadForm(show_stop_downloads='stop_download' in await request.form)

    #return await render_template('scrape_form.html', form=form)
    return await render_template('scrape_form.html', form=form, show_stop_downloads=show_stop_downloads)

@app.route('/form', methods=['GET', 'POST'])
async def submit():
    form = MyForm(await request.form, meta={'csrf': False})
    if form.validate_on_submit():
        return 'Success.'
    return await render_template('submit.html', form=form)

@app.route('/stop_downloads', methods=['POST'])
async def stop_downloads():
    # Handle the stop downloads request
    print('***** STOP DOWNLOAD TRIGGER ****')
    stop_event.set()

    # Return a response to the AJAX request
    return jsonify({'message': 'Downloads stopped successfully'})
# Preserve the ability to run in dev with a simple 'python app.py' command to start dev server
if __name__ == "__main__":
    app.run(loop=client.loop)
