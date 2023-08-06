import os

def get_download_dir(env, home):
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


def import_channels_from_file(file_path):
    channel_list = []
    try:
        with open(file_path, 'r') as f:
            channels = f.readlines()
            for channel in channels:
                # Remove any whitespace characters from the start and end of the line
                channel_id = int(channel.strip())
                channel_list.append(channel_id)
    except FileNotFoundError:
        print(f"Error: could not find channel file at {file_path}")

def add_channel_id_to_file(file_name, channel_id):
    with open(file_name, "a") as file:
        file.write(f"{channel_id}\n")

def remove_channel_id_from_file(file_name, channel_id):
    with open(file_name, "r+") as file:
        lines = file.readlines()
        file.seek(0)
        for line in lines:
            if line.strip() != str(channel_id):
                file.write(line)
        file.truncate()
