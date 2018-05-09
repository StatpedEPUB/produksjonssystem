#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import tempfile

from lxml import etree as ElementTree
from core.utils.metadata import Metadata
from core.utils.daisy_pipeline import DaisyPipelineJob

from core.pipeline import Pipeline

if sys.version_info[0] != 3 or sys.version_info[1] < 5:
    print("# This script requires Python version 3.5+")
    sys.exit(1)

class NlbpubToPef(Pipeline):
    uid = "nlbpub-to-pef"
    title = "NLBPUB til PEF"
    labels = [ "Punktskrift" ]
    publication_format = "Braille"
    
    def on_book_deleted(self):
        self.utils.report.info("Slettet bok i mappa: " + self.book['name'])
        self.utils.report.title = self.title + " HTML-kilde slettet: " + self.book['name']
    
    def on_book_modified(self):
        self.utils.report.info("Endret bok i mappa: " + self.book['name'])
        self.on_book()
    
    def on_book_created(self):
        self.utils.report.info("Ny bok i mappa: " + self.book['name'])
        self.on_book()
    
    def on_book(self):
        self.utils.report.attachment(None, self.book["source"], "DEBUG")
        
        
        # ---------- lag en kopi av filsettet ----------
        
        temp_htmldir_obj = tempfile.TemporaryDirectory()
        temp_htmldir = temp_htmldir_obj.name
        self.utils.filesystem.copy(self.book["source"], temp_htmldir)
        
        
        # ---------- finn HTML-fila ----------
        
        html_file = None
        for root, dirs, files in os.walk(temp_htmldir):
            for f in files:
                if f.endswith("html"):
                    html_file = os.path.join(root, f)
        if not html_file or not os.path.isfile(html_file):
            self.utils.report.error(self.book["name"] + ": Klarte ikke å finne en HTML-fil.")
            self.utils.report.title = self.title + ": " + self.book["name"] + " feilet 😭👎"
            return
        
        
        # ---------- bestem boknummer ----------
        
        html_xml = ElementTree.parse(html_file).getroot()
        identifier = html_xml.xpath("/*/*[local-name()='head']/*[@name='dc:identifier']")
        
        bookTitle = ""
        bookTitle = " (" + html_xml.xpath("string(/*/*[local-name()='head']/*[local-name()='title']/text())") + ") "
        
        identifier = identifier[0].attrib["content"] if identifier and "content" in identifier[0].attrib else None
        if not identifier:
            self.utils.report.error(self.book["name"] + ": Klarte ikke å finne boknummer i HTML-fil.")
            self.utils.report.title = self.title + ": " + self.book["name"] + " feilet 😭👎"
            return
        epub_identifier = html_xml.xpath("/*/*[local-name()='head']/*[@name='nlbprod:identifier.epub']")
        epub_identifier = epub_identifier[0].attrib["content"] if epub_identifier and "content" in epub_identifier[0].attrib else None
        
        # ---------- konverter til PEF ----------
        
        braille_arguments = {
            "fullskrift": {
                "html": html_file,
                "braille-standard": "(dots:6)(grade:0)",
                "line-spacing": "single",
                "duplex": "true"
            },
            "kortskrift": {
                "html": html_file,
                "braille-standard": "(dots:6)(grade:2)",
                "line-spacing": "single",
                "duplex": "true"
            },
            "lesetrening": {
                "html": html_file,
                "braille-standard": "(dots:6)(grade:0)",
                "line-spacing": "double",
                "duplex": "false"
            }
        }
        for braille_version in braille_arguments:
            pef_dir = None

            self.utils.report.info("Konverterer fra HTML til PEF (" + braille_version + ")...")
            dp2_job = DaisyPipelineJob(self, "nlb:html-to-pef", braille_arguments[braille_version])

            # get conversion report
            if os.path.isdir(os.path.join(dp2_job.dir_output, "preview-output-dir")):
                self.utils.filesystem.copy(os.path.join(dp2_job.dir_output, "preview-output-dir"), os.path.join(self.utils.report.reportDir(), "preview-" + braille_version))
                self.utils.report.attachment(None, os.path.join(self.utils.report.reportDir(), "preview-" + braille_version + "/" + identifier + ".pef.html"), "SUCCESS" if dp2_job.status == "DONE" else "ERROR")

            if dp2_job.status != "DONE":
                self.utils.report.info("Klarte ikke å konvertere boken")
                self.utils.report.title = self.title + ": " + identifier + " feilet 😭👎" + bookTitle
                return
            
            pef_dir = os.path.join(dp2_job.dir_output, "pef-output-dir")
            
            if not os.path.isdir(pef_dir):
                self.utils.report.info("Finner ikke den konverterte boken.")
                self.utils.report.title = self.title + ": " + identifier + " feilet 😭👎" + bookTitle
                return
            
            self.utils.report.info("Boken ble konvertert. Kopierer til PEF-arkiv.")
        
            archived_path = self.utils.filesystem.storeBook(pef_dir, identifier, subdir=braille_version)
            self.utils.report.attachment(None, archived_path, "DEBUG")
            self.utils.report.info(identifier + " ble lagt til i arkivet under PEF/" + braille_version + ".")

        self.utils.report.title = self.title + ": " + identifier + " ble konvertert 👍😄" + bookTitle


if __name__ == "__main__":
    NlbpubToPef().run()
