#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shutil
import tempfile
import traceback
import subprocess

from lxml import etree as ElementTree
from core.pipeline import Pipeline
from nlbpub_to_html import NlbpubToHtml
from core.utils.epub import Epub
from core.utils.xslt import Xslt

if sys.version_info[0] != 3 or sys.version_info[1] < 5:
    print("# This script requires Python version 3.5+")
    sys.exit(1)


class PrepareForDocx(Pipeline):
    uid = "prepare-for-docx"
    title = "Klargjør for DOCX"
    labels = ["e-bok"]
    publication_format = "XHTML"
    expected_processing_time = 8

    def on_book_deleted(self):
        self.utils.report.info("Slettet bok i mappa: " + self.book['name'])
        self.utils.report.title = self.title + " EPUB slettet: " + self.book['name']
        self.utils.report.should_email = False

    def on_book_modified(self):
        self.utils.report.info("Endret bok i mappa: " + self.book['name'])
        self.on_book()

    def on_book_created(self):
        self.utils.report.info("Ny bok i mappa: " + self.book['name'])
        self.on_book()

    def on_book(self):
        self.utils.report.attachment(None, self.book["source"], "DEBUG")
        epub = Epub(self, self.book["source"])

        epubTitle = ""
        try:
            epubTitle = " (" + epub.meta("dc:title") + ") "
        except Exception:
            pass

        # sjekk at dette er en EPUB
        if not epub.isepub():
            self.utils.report.title = self.title + ": " + self.book["name"] + " feilet 😭👎"
            return

        if not epub.identifier():
            self.utils.report.error(self.book["name"] + ": Klarte ikke å bestemme boknummer basert på dc:identifier.")
            self.utils.report.title = self.title + ": " + self.book["name"] + " feilet 😭👎"
            return

        # ---------- lag en kopi av EPUBen ----------

        temp_epubdir_obj = tempfile.TemporaryDirectory()
        temp_epubdir = temp_epubdir_obj.name
        self.utils.filesystem.copy(self.book["source"], temp_epubdir)
        temp_epub = Epub(self, temp_epubdir)

        # ---------- gjør tilpasninger i HTML-fila med XSLT ----------

        opf_path = temp_epub.opf_path()
        if not opf_path:
            self.utils.report.error(self.book["name"] + ": Klarte ikke å finne OPF-fila i EPUBen.")
            self.utils.report.title = self.title + ": " + self.book["name"] + " feilet 😭👎" + epubTitle
            return
        opf_path = os.path.join(temp_epubdir, opf_path)
        opf_xml = ElementTree.parse(opf_path).getroot()

        html_file = opf_xml.xpath("/*/*[local-name()='manifest']/*[@id = /*/*[local-name()='spine']/*[1]/@idref]/@href")
        html_file = html_file[0] if html_file else None
        if not html_file:
            self.utils.report.error(self.book["name"] + ": Klarte ikke å finne HTML-fila i OPFen.")
            self.utils.report.title = self.title + ": " + self.book["name"] + " feilet 😭👎" + epubTitle
            return
        html_dir = os.path.dirname(opf_path)
        html_file = os.path.join(html_dir, html_file)
        if not os.path.isfile(html_file):
            self.utils.report.error(self.book["name"] + ": Klarte ikke å finne HTML-fila.")
            self.utils.report.title = self.title + ": " + self.book["name"] + " feilet 😭👎" + epubTitle
            return

        temp_html_obj = tempfile.NamedTemporaryFile()
        temp_html = temp_html_obj.name

        xslt = Xslt(self,
                    stylesheet=os.path.join(Xslt.xslt_dir, PrepareForDocx.uid, "prepare-for-docx.xsl"),
                    source=html_file,
                    target=temp_html)
        if not xslt.success:
            self.utils.report.title = self.title + ": " + epub.identifier() + " feilet 😭👎" + epubTitle
            return
        shutil.copy(temp_html, html_file)

        archived_path = self.utils.filesystem.storeBook(temp_epubdir, epub.identifier())
        self.utils.report.attachment(None, archived_path, "DEBUG")
        self.utils.report.info(epub.identifier() + " ble lagt til i 'klargjort for DOCX'-arkivet.")
        self.utils.report.title = self.title + ": " + epub.identifier() + " ble konvertert 👍😄" + epubTitle


if __name__ == "__main__":
    PrepareForDocx().run()
