# RSS 基础设施工具

import requests

class rss_main():

    def __init__(self,url,payload):
        self.re = requests.get(url, params=payload)
    def search(url, name):
        pass