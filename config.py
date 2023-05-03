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
