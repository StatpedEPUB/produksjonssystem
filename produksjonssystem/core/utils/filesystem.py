# -*- coding: utf-8 -*-

import os
import shutil
import subprocess
import socket
import re
import urllib.request
import tempfile
from pathlib import Path

class Filesystem():
    """Operations on files and directories"""
    
    pipeline = None
    
    _i18n = {
        "Storing": "Lagrer",
        "in": "i",
        "exists in": "finnes i",
        "already; existing copy will be deleted": "fra før; eksisterende kopi blir slettet",
        "Running": "Kjører"
    }
    
    def __init__(self, pipeline):
        self.pipeline = pipeline
    
    def copy(self, source, destination):
        """Copy the `source` file or directory to the `destination`"""
        assert source, "Filesystem.copy(): source must be specified"
        assert destination, "Filesystem.copy(): destination must be specified"
        assert os.path.isdir(source) or os.path.isfile(source), "Filesystem.copy(): source must be either a file or a directory: " + str(source)
        if os.path.isdir(source):
            try:
                if os.path.exists(destination):
                    if os.listdir(destination):
                        self.pipeline.utils.report.warn(os.path.basename(destination) + " " + self._i18n["exists in"] + " " + os.path.dirname(destination) + " " + self._i18n["already; existing copy will be deleted"])
                    shutil.rmtree(destination)
                shutil.copytree(source, destination)
            except shutil.Error as errors:
                warnings = []
                for arg in errors.args[0]:
                    src, dst, e = arg
                    if e.startswith("[Errno 95]") and "/gvfs/" in dst:
                        warnings.append("WARN: Unable to set permissions on manually mounted samba shares")
                    else:
                        warnings.append(None)
                warnings = list(set(warnings)) # distinct warnings
                for warning in warnings:
                    if warning is not None:
                        self.pipeline.utils.report.warn(warning)
                if None in warnings:
                    raise
        else:
            shutil.copy(source, destination)
    
    def storeBook(self, source, book_id, move=False, subdir=None):
        """Store `book_id` from `source` into `pipeline.dir_out`"""
        self.pipeline.utils.report.info(self._i18n["Storing"] + " " + book_id + " " + self._i18n["in"] + " " + self.pipeline.dir_out + "...")
        assert book_id
        assert book_id.strip()
        assert book_id != "."
        assert not ".." in book_id
        assert not "/" in book_id
        assert not subdir or not ".." in subdir
        assert not subdir or not "/" in subdir
        dir_out = self.pipeline.dir_out
        if subdir:
            dir_out = os.path.join(dir_out, subdir)
        target = os.path.join(dir_out, book_id)
        if os.path.exists(target):
            self.pipeline.utils.report.warn(book_id + " " + self._i18n["exists in"] + " " + dir_out + " " + self._i18n["already; existing copy will be deleted"])
            shutil.rmtree(target)
        if move:
            shutil.move(source, target)
        else:
            self.copy(source, target)
        
        # update modification time for directory
        f = tempfile.NamedTemporaryFile(suffix="-dirmodified", dir=target).name
        Path(f).touch()
        os.remove(f)
        
        return target
    
    def deleteSource(self):
        if os.path.isdir(self.pipeline.book["source"]):
            shutil.rmtree(self.pipeline.book["source"])
        elif os.path.isfile(self.pipeline.book["source"]):
            os.remove(self.pipeline.book["source"])
    
    def run(self, args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, cwd=None, timeout=600, check=True):
        """Convenience method for subprocess.run, with our own defaults"""
        if not cwd:
            cwd = self.pipeline.dir_in
        
        self.pipeline.utils.report.debug(self._i18n["Running"] + ": "+(" ".join(args) if isinstance(args, list) else args))
        
        completedProcess = None
        try:
            completedProcess = subprocess.run(args, stdout=stdout, stderr=stderr, shell=shell, cwd=cwd, timeout=timeout, check=check)
            
            self.pipeline.utils.report.debug("---- stdout: ----")
            self.pipeline.utils.report.debug(completedProcess.stdout.decode("utf-8").strip())
            self.pipeline.utils.report.debug("-----------------")
            self.pipeline.utils.report.debug("---- stderr: ----")
            self.pipeline.utils.report.debug(completedProcess.stderr.decode("utf-8").strip())
            self.pipeline.utils.report.debug("-----------------")
            
        except subprocess.CalledProcessError as e:
            self.pipeline.utils.report.debug("---- stdout: ----")
            self.pipeline.utils.report.debug(e.stdout.decode("utf-8").strip())
            self.pipeline.utils.report.debug("-----------------")
            self.pipeline.utils.report.debug("---- stderr: ----")
            self.pipeline.utils.report.debug(e.stderr.decode("utf-8").strip())
            self.pipeline.utils.report.debug("-----------------")
            raise
        
        return completedProcess
    
    @staticmethod
    def ismount(path):
        return True if Filesystem.getdevice(path) else False
    
    @staticmethod
    def getdevice(path):
        path = os.path.normpath(path)
        
        with open('/proc/mounts','r') as f:
            for line in f.readlines():
                l = line.split()
                if l[0].startswith("/") and l[1] == path:
                    #l[0] = "//x.x.x.x/sharename/optionalsubpath"
                    #l[1] = "/mount/point"
                    return re.sub("^//", "smb://", l[0])
        
        x_dir = os.getenv("XDG_RUNTIME_DIR")
        if x_dir:
            for mount in [os.path.join(x_dir, "gvfs", m) for m in os.listdir(os.path.join(x_dir, "gvfs"))]:
                if mount == path:
                    # path == "$XDG_RUNTIME_DIR/gvfs/smb-share:server=x.x.x.x,share=sharename"
                    return re.sub(",share=", "/", re.sub("^smb-share:server=", "smb://", os.path.basename(path)))
        
        return None
    
    @staticmethod
    def networkpath(path):
        path = os.path.normpath(path)
        if path == ".":
            path = ""
        
        levels = path.split(os.path.sep)
        possible_mount_points = ["/".join(levels[:i+1]) for i in range(len(levels))][1:]
        possible_mount_points.reverse()
        
        smb = None
        for possible_mount_point in possible_mount_points:
            smb = Filesystem.getdevice(possible_mount_point)
            if smb:
                smb = smb + path[len(possible_mount_point):]
                break
        
        if not smb:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            localhost = s.getsockname()[0]
            s.close()
            smb = "smb://" + localhost + path
        
        smb = re.sub("^(smb:/+[^/]+).*", "\\1", smb) + urllib.request.pathname2url(re.sub("^smb:/+[^/]+/*(/.*)$", "\\1", smb))
        
        file = re.sub("^smb:", "file:", smb)
        unc = re.sub("/", r"\\", re.sub("^smb:", "", smb))
        return smb, file, unc
    
    # in case you want to override something
    def translate(self, english_text, translated_text):
        self._i18n[english_text] = translated_text
    