class Config:
    pass

class DevelopmentConfig(Config):
    DOWNLOADS = '/volumes/G-DRIVE-SSD/Software/telegram'

class ProductionConfig(Config):
    DOWNLOADS='/media/veracrypt1/telegram'