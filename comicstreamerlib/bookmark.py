# coding=utf-8

"""
ComicStreamer bookmark manager thread class
"""

import threading
import select
import sys
import logging
import platform
import Queue
import datetime

from database import Comic

class Bookmark(threading.Thread):
    def __init__(self, dm):
        super(Bookmark, self).__init__()

        self.queue = Queue.Queue(0)
        self.quit = False
        self.dm = dm
        
    def stop(self):
        self.quit = True
        self.join()
        
    def setBookmark(self, comic_id, pagenum):
        # for now, don't defer the bookmark setting, maybe it's not needed
        self.actualSetBookmark( comic_id, pagenum)
        #self.queue.put((comic_id, pagenum))
        
    def removeBookmark(self, comic_id, pagenum):
        pass
        # for now, don't defer the bookmark setting, maybe it's not needed
        #self.actualSetBookmark( comic_id, pagenum)
        #self.queue.put((comic_id, pagenum))
        
    def run(self):
        logging.debug("Bookmark: Started")
        pagenum = 0
        while True:
            try:
                (comic_id, pagenum) = self.queue.get(block=True, timeout=1)
            except:
                comic_id = None
                
            self.actualSetBookmark(comic_id, pagenum)
                        
            if self.quit:
                break
            
        logging.debug("Bookmark: Stopped")

    def actualSetBookmark(self, comic_id, pagenum):
                
        if comic_id is not None:
            session = self.dm.Session()
    
            obj = session.query(Comic).filter(Comic.id == int(comic_id)).first()
            if obj is not None:
                try:
                    if pagenum.lower() == "clear":
                        obj.lastread_ts =  None
                        obj.lastread_page = None
                    elif int(pagenum) < obj.page_count:
                        obj.lastread_ts = datetime.datetime.utcnow()
                        obj.lastread_page = int(pagenum)
                        #logging.debug("bookmark: about to commit boommak ts={0}".format(obj.lastread_ts))
                except Exception:
                    logging.error("Bookmark: Problem marking page {} on comic {}".format(pagenum, comic_id))
                else:
                    session.commit()
                    
            session.close()

#-------------------------------------------------

