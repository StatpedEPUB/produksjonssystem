# -*- coding: utf-8 -*-

import os
import shutil
import subprocess
import zipfile

class Filesystem():
    """Operations on files and directories"""
    
    book = None
    report = None
    
    def __init__(self, book, report):
        self.book = book
        self.report = report
    
    def copy(self, source, destination):
        """Copy the `source` file or directory to the `destination`"""
        try:
            shutil.copytree(source, destination)
        except OSError as e:
            if e.errno == errno.ENOTDIR:
                shutil.copy(source, destination)
            else:
                raise
    
    def storeBook(self, archive_dir, source, book_id):
        """Store `book_id` from `source` into `archive_dir`"""
        self.report.info("Storing " + book_id + " in " + archive_dir + "...")
        assert book_id
        assert book_id.strip()
        assert book_id != "."
        assert not ".." in book_id
        assert not "/" in book_id
        target = os.path.join(archive_dir, book_id)
        if os.path.exists(target):
            self.report.warn(book_id + " finnes i " + archive_dir + " fra før; eksisterende kopi blir slettet")
            shutil.rmtree(target)
        self.copy(source, target)
    
    def run(self, args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, cwd=None, timeout=600, check=True):
        """Convenience method for subprocess.run, with our own defaults"""
        if not cwd:
            cwd = self.book["base"]
        print("running: "+(" ".join(args) if isinstance(args, list) else args))
        return subprocess.run(args, stdout=stdout, stderr=stderr, shell=shell, cwd=cwd, timeout=timeout, check=check)
        