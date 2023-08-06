"""Load all user defined config and env vars."""

import logging
import os
import sys
import importlib

from typing import Dict, List, Optional, Union
from dotenv import load_dotenv
from pydantic import BaseModel, validator  # pylint: disable=no-name-in-module
from utils import import_channels_from_file

load_dotenv()
CONFIG_FILE_NAME = "tgcf.config.json"

class LoginConfig(BaseModel):
    API_ID: str = os.environ.get('API_ID')
    API_HASH: str = os.environ.get('API_HASH')
    SESSION_NAME: str = os.environ.get('SESSION_NAME')


class MegaConfig(BaseModel):
    MEGA_EMIAL: str=os.environ.get('MEGA_EMAIL')
    MEGA_PASSWORD: str=os.environ.get('MEGA_PASSWORD')


class ServiceConfig(BaseModel):
    polling_channels: List[Union[int, str]
                           ] = import_channels_from_file('./channels.txt')


class Config(object):
    TESTING = False


class ProductionConfig(Config):
    DEVELOPMENT = False
    DOWNLOADS = '/media/veracrypt1/telegram'



class StagingConfig(Config):
    DEVELOPMENT = True


class DevelopmentConfig(Config):
    FLASK_ENV = 'development'
    DEVELOPMENT = True
    DOWNLOADS = '/volumes/G-DRIVE-SSD/Software/telegram'


class TestingConfig(Config):
    TESTING = True


class MasterConfig (BaseModel):
    secret_key: str = os.environ.get('SECRET_KEY')
    login: LoginConfig = LoginConfig()
    mega: MegaConfig = MegaConfig()
    service: ServiceConfig = ServiceConfig()


def write_config_to_file(config: Config):
    with open(CONFIG_FILE_NAME, "w", encoding="utf8") as file:
        file.write(config.json())


def read_config(count=1) -> MasterConfig:
    #Load the configuration from text file.
    #CREATES INSTANCE OF MASTERCONFIG
    if count > 3:
        logging.warning("Failed to read config, returning default config")
        return MasterConfig()
    if count != 1:
        logging.info(f"Trying to read config time:{count}")
    try:
        with open(CONFIG_FILE_NAME, encoding="utf8") as file:
            return MasterConfig.model_validate_json(file.read())
    except Exception as err:
        logging.warning(err)
        create_config_file_if_absent()
        return read_config(count=count + 1)


#def get_secret_key() -> str:
#    return os.environ.get('SECRET_KEY')


def get_environ_class():
    envclass_name, envsubclass_name = os.environ.get(
        "APP_SETTINGS", 'config.DevelopmentConfig').split(".")
    envclass = importlib.import_module(envclass_name)
    return getattr(envclass, envsubclass_name)


def create_config_file_if_absent():
    if CONFIG_FILE_NAME in os.listdir():
        logging.info(f"{CONFIG_FILE_NAME} detected!")
    else:
        logging.info(
            "config file not found. mongo not found. creating local config file."
        )
        cfg = MasterConfig()
        write_config_to_file(cfg)
        logging.info(f"{CONFIG_FILE_NAME} created!")


CONFIG = read_config()