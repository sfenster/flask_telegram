import os
import asyncio
import importlib
import sqlite3
import dotenv
from mega import Mega
from quart import Quart, Response
from telethon import TelegramClient, events

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
            video_file = await client.download_media(message, file=file_path, progress_callback=lambda d, t: print(f'{d}/{t} bytes downloaded ({d/t*100:.2f}%)'))
            print(f'Video saved to {file_path}')
            # Add the video ID to the downloaded_videos table
            with sqlite3.connect('downloads.db') as conn:
                create_downloads_table(conn)
                add_to_downloaded(conn, message.video.id)
            # Upload the video file to Mega.nz
            #try:
            #    if mega_email and mega_password:
            #        mega_folder = mega_login.find('Telegram Videos')
            #        if not mega_folder:
            #            mega_folder = mega_login.create_folder('Telegram Videos')
            #        mega_file = mega_login.upload(video_file, mega_folder[0])
                    
                    # Delete the local video file
            #        os.remove(video_file)

            #        print(f"Downloaded and uploaded video '{message.video.id}' to Mega.nz file '{mega_file['name']}' in folder '{mega_folder[0]['astring']}'")       
            #except Exception as e:
             #   print (e)
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



# Preserve the ability to run in dev with a simple 'python app.py' command to start dev server
if __name__ == "__main__":

    # By default, `Quart.run` uses `asyncio.run()`, which creates a new asyncio
    # event loop. If we create the `TelegramClient` before, `telethon` will
    # use `asyncio.get_event_loop()`, which is the implicit loop in the main
    # thread. These two loops are different, and it won't work.
    #
    # So, we have to manually pass the same `loop` to both applications to
    # make 100% sure it works and to avoid headaches.
    #
    # Quart doesn't seem to offer a way to run inside `async def`
    # (see https://gitlab.com/pgjones/quart/issues/146) so we must
    # run and block on it last.
    #
    # This example creates a global client outside of Quart handlers.
    # If you create the client inside the handlers (common case), you
    # won't have to worry about any of this.
    app.run(loop=client.loop)
