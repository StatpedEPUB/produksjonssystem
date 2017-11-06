#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import tempfile
import time
from datetime import datetime, timezone
import subprocess
import shutil
import re
from email.headerregistry import Address

from core.pipeline import Pipeline

if sys.version_info[0] != 3 or sys.version_info[1] < 5:
    print("# This script requires Python version 3.5+")
    sys.exit(1)

class IncomingNordic(Pipeline):
    title = "Validering av Nordisk EPUB 3"
    
    epub_in = None
    valid_out = None
    invalid_out = None
    report_out = None
    
    email_smtp = {
        "host": "smtp.gmail.com",
        "port": "587",
        "user": os.environ["GMAIL_USERNAME"],
        "pass": os.environ["GMAIL_PASSWORD"]
    }
    email_sender = Address("NLB", "noreply@nlb.no")
    email_recipients = [ Address("Jostein Austvik Jacobsen", "jostein@nlb.no") ]
    
    dp2_home = "/home/jostein/Skrivebord/daisy-pipeline" # "/opt/daisy-pipeline2"
    dp2_cli = dp2_home + "/cli/dp2"
    saxon_cli = "java -jar " + os.path.join(dp2_home, "system/framework/org.daisy.libs.saxon-he-9.5.1.5.jar")
    
    first_job = True # Will be set to false after first job is triggered
    
    def __init__(self, epub_in, valid_out, invalid_out, report_out, stop_after_first_job=False):
        self.queue = [] # discards pre-existing files
        self.epub_in = epub_in
        self.valid_out = valid_out
        self.invalid_out = invalid_out
        self.report_out = report_out
        
        super().__init__(epub_in, stop_after_first_job=stop_after_first_job)
    
    def on_book_moved(self, book):
        pass # do nothing
    
    def on_book_deleted(self, book):
        pass # do nothing
    
    def on_book_modified(self, book):
        self.utils.report.info("Endret bok i mappa: "+book['name'])
        self.on_book(book)
    
    def on_book_created(self, book):
        self.utils.report.info("Ny bok i mappa: "+book['name'])
        self.on_book(book)
    
    def on_book(self, book):
        if self.first_job:
            try:
                # start engine if it's not started already
                process = self.utils.filesystem.run([self.dp2_cli, "help"], shell=True)
                
            except subprocess.TimeoutExpired as e:
                self.utils.report.info("Oppstart av Pipeline 2 tok for lang tid og ble derfor stoppet.")
                
            except subprocess.CalledProcessError as e:
                self.utils.report.debug("En feil oppstod når Pipeline 2 startet. Vi venter noen sekunder og håper det går bra alikevel...")
                time.sleep(5)
            
            self.first_job = False
        
        # Unik identifikator for denne jobben
        uid = book["name"] + "-" + datetime.now(timezone.utc).strftime("%F_%H-%M-%S.") + str(round((time.time() % 1) * 1000)).zfill(3)
        
        # Bruk unik identifikator for rapport-mappen
        report_dir = os.path.join(self.report_out, uid)
        os.makedirs(report_dir)
        
        # Bruk sub-mapper for å unngå overskriving og filnavn-kollisjoner
        workspace_dir_object = tempfile.TemporaryDirectory()
        workspace_dir = workspace_dir_object.name
        
        book_id = book["name"]
        book_dir = os.path.join(workspace_dir, book_id)
        
        # unzip EPUB hvis den er zippet
        if os.path.isfile(book["source"]) and book["name"].endswith(".epub"):
            book_id = book["name"].replace(".epub","")
            book_dir = os.path.join(workspace_dir, book_id)
            self.utils.report.info("Pakker ut " + book["name"])
            os.makedirs(book_dir)
            self.utils.epub.unzip(book["source"], book_dir)
            
        # eller bare kopier filesettet hvis den ikke er zippet
        elif os.path.isdir(book["source"]):
            os.makedirs(book_dir)
            self.utils.filesystem.copy(book["source"], book_dir)
            
        # hvis det hverken er en EPUB eller en mappe så er noe galt; avbryt
        else:
            self.utils.report.info(book_id + " er hverken en \".epub\"-fil eller en mappe.")
            self.utils.filesystem.storeBook(self.invalid_out, book["source"], uid, move=True)
            self.utils.report.email(self.title + ": " + book_id + " feilet 😭👎",
                                    self.email_sender,
                                    self.email_recipients,
                                    self.email_smtp,
                                    os.path.join(report_dir, "log.txt"))
            return
        
        # EPUBen må inneholde en "EPUB/package.opf"-fil (en ekstra sjekk for å være sikker på at dette er et EPUB-filsett)
        if not os.path.isfile(os.path.join(book_dir, "EPUB/package.opf")):
            self.utils.report.info(book_id + ": EPUB/package.opf eksisterer ikke; kan ikke validere EPUB.")
            self.utils.filesystem.storeBook(self.invalid_out, book["source"], uid, move=True)
            self.utils.report.email(self.title + ": " + book_id + " feilet 😭👎",
                                    self.email_sender,
                                    self.email_recipients,
                                    self.email_smtp,
                                    os.path.join(report_dir, "log.txt"))
            return
        
        # sørg for at filrettighetene stemmer
        os.chmod(book_dir, 0o777)
        for root, dirs, files in os.walk(book_dir):
            for d in dirs:
                os.chmod(os.path.join(root, d), 0o777)
            for f in files:
                os.chmod(os.path.join(root, f), 0o666)
        
        book_file = os.path.join(workspace_dir, book_id + ".epub")
        
        # lag en zippet versjon av EPUBen også
        self.utils.report.info("Pakker sammen " + book_id + "...")
        self.utils.epub.zip(book_dir, book_file)
        
        # -- Kommer vi hit så er vi ganske sikre på at vi har med et EPUB-filsett å gjøre. --
        
        job_dir  = os.path.join(workspace_dir, "nordic-epub3-validate/")
        os.makedirs(job_dir)

        result_dir = os.path.join(job_dir, "result/")
        
        job_id = None
        result_status = None
        
        try:
            # run validator
            process = self.utils.filesystem.run([self.dp2_cli, "nordic-epub3-validate", "--epub", book_file, "--output", result_dir, "-p"])
            
            # get dp2 job id
            job_id = None
            for line in process.stdout.decode("utf-8").split("\n"):
                # look for: Job {id} sent to the server
                m = re.match("^Job (.*) sent to the server$", line)
                if m:
                    job_id = m.group(1)
                    break
            assert job_id, "Could not find the job ID for the validation job"
            
            # get validation log (the run method will log stdout/stderr as debug output)
            process = self.utils.filesystem.run([self.dp2_cli, "log", job_id])
            
            # get validation status
            process = self.utils.filesystem.run([self.dp2_cli, "status", job_id])
            result_status = None
            for line in process.stdout.decode("utf-8").split("\n"):
                # look for: Job {id} sent to the server
                m = re.match("^Status: (.*)$", line)
                if m:
                    result_status = m.group(1)
                    break
            assert result_status, "Klarte ikke å finne jobb-status for validerings-jobben"
            self.utils.report.debug("Pipeline 2 status: " + result_status)
            
            # get validation report
            with open(os.path.join(result_dir, "html-report/report.xhtml"), 'r') as result_report:
                self.utils.report.attachment(result_report.readlines(), os.path.join(report_dir, "report.html"), "SUCCESS" if result_status == "DONE" else "ERROR")
            
        except subprocess.TimeoutExpired as e:
            self.utils.report.info("Validering av " + book_id + " tok for lang tid og ble derfor stoppet.")
            self.utils.filesystem.storeBook(self.invalid_out, book["source"], uid, move=True)
            self.utils.report.email(self.title + ": " + book_id + " feilet 😭👎",
                                    self.email_sender,
                                    self.email_recipients,
                                    self.email_smtp,
                                    os.path.join(report_dir, "log.txt"))
            return
            
        finally:
            if job_id:
                try:
                    process = self.utils.filesystem.run([self.dp2_cli, "delete", job_id])
                except subprocess.TimeoutExpired as e:
                    self.utils.report.warn("Klarte ikke å slette Pipeline 2 jobb med ID " + job_id)
                    pass
        
        if result_status != "DONE":
            self.utils.report.info("Klarte ikke å validere boken")
            self.utils.filesystem.storeBook(self.invalid_out, book["source"], uid, move=True)
            self.utils.report.email(self.title + ": " + book_id + " feilet 😭👎",
                                    self.email_sender,
                                    self.email_recipients,
                                    self.email_smtp,
                                    os.path.join(report_dir, "log.txt"))
            return
        
        self.utils.report.info("Boken er valid. Kopierer til master-arkiv.")
        
        archived_path = self.utils.filesystem.storeBook(self.valid_out, book_dir, book_id)
        self.utils.report.attachment(None, archived_path, "DEBUG")
        self.utils.filesystem.deleteSource()
        self.utils.report.info(book_id+" ble lagt til i master-arkivet.")
        self.utils.report.email(self.title + ": " + book_id + " er valid 👍😄",
                                self.email_sender,
                                self.email_recipients,
                                self.email_smtp,
                                os.path.join(report_dir, "log.txt"))
        
        # TODO:
        # - self.utils.epubCheck på mottatt EPUB
        # - EPUB 3 Accessibility Checker på mottatt EPUB
        # - separat pipeline(?):
        #   - Konverter til NLBPUB
        #       if self.utils.epub.meta(book_dir, "nordic:guidelines") == "2015-1":
        #           nordic-epub3-to-nlbpub (= preprocessing + epub-to-nlbpub ?)
        #       else:
        #           epub-to-nlbpub
        #   - self.utils.epubCheck på NLBPUB
        #   - EPUB 3 Accessibility Checker på NLBPUB
        # - separat pipeline: EPUB til DTBook
        # - separat pipeline: EPUB til HTML
        # - separat pipeline: EPUB til innlesnings-EPUB
        # - separat pipeline: Zippet versjon av EPUB-master

if __name__ == "__main__":
    epub_in = os.environ.get("DIR_IN")
    valid_out = os.environ.get("DIR_OUT_VALID")
    invalid_out = os.environ.get("DIR_OUT_INVALID")
    report_out = os.environ.get("DIR_OUT_REPORT")
    
    assert epub_in != None and len(epub_in) > 0, "Miljøvariabelen DIR_IN må være spesifisert, og må peke på en mappe."
    assert valid_out != None and len(valid_out) > 0 and os.path.exists(valid_out), "Miljøvariabelen DIR_OUT_VALID må være spesifisert, og må peke på en mappe som finnes."
    assert invalid_out != None and len(invalid_out) > 0 and os.path.exists(invalid_out), "Miljøvariabelen DIR_OUT_INVALID må være spesifisert, og må peke på en mappe som finnes."
    assert report_out != None and len(report_out) > 0 and os.path.exists(report_out), "Miljøvariabelen DIR_OUT_REPORT må være spesifisert, og må peke på en mappe som finnes."
    
    stop_after_first_job = False
    if os.environ.get("STOP_AFTER_FIRST_JOB"):
        stop_after_first_job = True
    
    pipeline = IncomingNordic(epub_in, valid_out, invalid_out, report_out, stop_after_first_job=stop_after_first_job)
    
    pipeline.run(1)
