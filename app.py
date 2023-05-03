import os
import asyncio
import importlib
import sqlite3
from quart import Quart, Response
from telethon import TelegramClient, events

api_id = os.environ.get('API_ID')
api_hash = os.environ.get('API_HASH')
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
channel = [-1001576804766,
           -1001529959609,
           -1001835054584,
           -1001748083163,
           -1001756874600,
           -1001572063931,
           -1001807527093,
           -1001860438055,
           -1001651360534,
           -1001536882363,
           -1001983253182,
           -1001873099235,
           -1001750769512,
           -1001726765333,
           -1001878723718,
           -1001181167174,
           -1001699507129,
           -1001883775698
           ]

# Get the environment object for config.py using the 'APP_SETTINGS' env variable
envclass_name, envsubclass_name = os.environ.get(
    "APP_SETTINGS", 'config.DevelopmentConfig').split(".")
envclass = importlib.import_module(envclass_name)
env = getattr(envclass, envsubclass_name)


def get_download_dir():
    dl = getattr(env, 'DOWNLOADS')
    dl = dl.replace("~", home)
    try:
        # Attempt to open the file for writing
        # with open(dl, 'w'):
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
        cursor.execute('SELECT id FROM downloaded_videos WHERE id=?', (video_id,))
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


async def download_video(client, message, file_path):
    # Download the video and track the download progress
    try:
        # Get the duration of the video
        duration = message.file.duration

        # Only download the video if it's longer than 10 seconds
        if duration > video_min_duration:
            await client.download_media(message, file=file_path, progress_callback=lambda d, t: print(f'{d}/{t} bytes downloaded ({d/t*100:.2f}%)'))
            print(f'Video saved to {file_path}')
            # Add the video ID to the downloaded_videos table
            with sqlite3.connect('downloads.db') as conn:
                create_downloads_table(conn)
                add_to_downloaded(conn, message.video.id)
        else:
            print(
                f'Video duration is {duration}s, which is shorter than 10s. Skipping download.')
    except Exception as e:
        print(f'Error: {str(e)}')


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


@app.before_serving
async def startup():
    global downloads
    downloads = get_download_dir()
    print(f'download directory: {downloads}')
    await client.start()
    client.add_event_handler(handle_video, events.NewMessage(chats=channel))
    # create task to keep client running
    asyncio.create_task(client.run_until_disconnected())



@app.route("/")
async def index():
    return "Hello, world!"


@app.route("/channels")
async def channels():
    await get_dialogs()
    output_str = ""
    for channel in channels_queue:
        output_str += f"id: {channel['id']}, title: {channel['title']}\n"
    # OPTIONS FOR RUNNING BLOCKING CODE

    # METHOD 1 (for synchronout blocking code in a separate thread)
    #   loop = asyncio.get_running_loop()
    #   await loop.run_in_executor(None, (init_dialog())
    #   VARIATION FOR ASYNC CODE: await loop.run_in_executor(None, lambda: asyncio.run(init_dialog()))

    # METHOD 2 (SHORTER)
    # await asyncio.to_thread(func_call) can run synchronous functions in a separate thread
    # equivilant of 'await loop.run_in_executor(None, func_call)'
    # await asyncio.to_thread(init_dialog)
    return Response(output_str, mimetype="text/plain")


@app.route("/start-polling")
async def start_polling():
    global task
    if task is None or task.done():
        task = asyncio.create_task(client.run_until_disconnected())
        return "Polling started"
    else:
        return "Polling already running"


@app.route("/stop-polling")
async def stop_polling():
    global task
    if task is not None and not task.done():
        task.cancel()
        return "Polling stopped"
    else:
        return "Polling not running"



# Preserve the ability to run in dev with a simple 'python app.py' command to start dev server
if __name__ == "__main__":
    app.run()
