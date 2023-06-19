import os
import dotenv
import asyncio
import threading
from mangum import Mangum
from quart import Quart, jsonify
from telethon import TelegramClient

dotenv.load_dotenv()
api_id = os.environ.get('API_ID')
api_hash = os.environ.get('API_HASH')
session_name = 'flask_api_session'

app = Quart(__name__)

client = TelegramClient(session=session_name, api_id=api_id, api_hash=api_hash)
channels_queue = []  # to store the channels received from the Telegram client


@app.route("/")
async def index():
    return "Hello, world!"


@app.route('/channels', methods=['GET'])
async def channels():
    #t1 = client.loop.create_task(init_dialog())
    #await t1
 #   loop = asyncio.get_running_loop()
 #   loop.run_in_executor(None, lambda: asyncio.run(init_dialog()))
 
    # asyncio.to_thread can run synchronous functions in a separate thread
    # equivilant of 'await loop.run_in_executor(None, func_call)'
    # await asyncio.to_thread(init_dialog)
    await init_dialog()
    return jsonify({"channels": channels_queue})


async def start_telegram_client():
    global client, channels_queue
    await client.start()
    #async for dialog in client.iter_dialogs():
    #    channels_queue.append({'id': dialog.id, 'title': dialog.title})


def run_async_loop_in_thread():
    asyncio.run(async_for_loop())

async def async_for_loop():
    global channels_queue
    async for dialog in client.iter_dialogs():
        channels_queue.append({'id': dialog.id, 'title': dialog.title})

async def init_dialog():
    t = threading.Thread(target=run_async_loop_in_thread)
    t.start()
    for channel in channels_queue:
        print(channel)

handler = Mangum(app)  # optionally set debug=True
client.loop.run_until_complete(start_telegram_client())

# Preserve the ability to run in dev with a simple 'python app.py' command to start dev server
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
