# Telegram-related and other aynchronous functions to support the application

from quart import Response
from telethon import TelegramClient, events, errors
from telethon.tl.types import DocumentAttributeVideo

# Global lists to store the channels and groups
all_channels_and_groups = []
owned_channels_and_groups = []
postable_channels_and_groups = []


async def populate_channel_lists(client):
    global all_channels_and_groups, owned_channels_and_groups, postable_channels_and_groups
    
    #Empty all lists of previous values
    all_channels_and_groups.clear()
    owned_channels_and_groups.clear()
    postable_channels_and_groups.clear()

    # Retrieve all dialogs (channels and chats)
    async for dialog in client.iter_dialogs():
        # if isinstance(dialog.entity, Channel):
        try:
            if dialog.is_channel:
                # Add the channel or group to the all_channels_and_groups list
                all_channels_and_groups.append(dialog)
                creator = dialog.entity.creator
            # Check if you are an administrator in the channel or group
            if creator == True:
                # You own the channel or group
                owned_channels_and_groups.append(dialog)
            if dialog.is_group:
                # You have posting rights in the channel or group
                postable_channels_and_groups.append(dialog)
        except errors.ChatAdminRequiredError as e:
            # Handle chat admin required errors, if necessary
            print(f"Admin required: {e}")
        except errors.RPCError as e:
            # Handle other RPC errors, if necessary
            print(f"RPC error: {e}")


async def return_channels_as_string(client) -> str:
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
    return Response(output_str, mimetype="text/plain")
