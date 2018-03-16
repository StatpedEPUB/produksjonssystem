#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import time
import shutil
import tempfile
import subprocess
import pathlib

from lxml import etree as ElementTree
from datetime import datetime, timezone
from core.pipeline import Pipeline
from core.utils.epub import Epub
from core.utils.xslt import Xslt
from update_metadata import UpdateMetadata

if sys.version_info[0] != 3 or sys.version_info[1] < 5:
    print("# This script requires Python version 3.5+")
    sys.exit(1)

class NLBpubToDocx(Pipeline):
    uid = "nlbpub-to-docx"
    title = "NLBPUB til DOCX"

    xslt_dir = os.path.realpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "xslt"))

    def on_book_deleted(self):
        self.utils.report.info("Slettet bok i mappa: " + self.book['name'])
        self.utils.report.title = self.title + " EPUB master slettet: " + self.book['name']

    def on_book_modified(self):
        self.utils.report.info("Endret bok i mappa: " + self.book['name'])
        self.on_book()

    def on_book_created(self):
        self.utils.report.info("Ny bok i mappa: " + self.book['name'])
        self.on_book()

    def on_book(self):
        self.utils.report.attachment(None, self.book["source"], "DEBUG")
        epub = Epub(self, self.book["source"])

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


        # ---------- oppdater metadata ----------

        self.utils.report.info("Oppdaterer metadata...")
        updated = UpdateMetadata.update(self, temp_epub, publication_format="XHTML")
        if isinstance(updated, bool) and updated == False:
            self.utils.report.title = self.title + ": " + temp_epub.identifier() + " feilet 😭👎"
            return


        # ---------- gjør tilpasninger i HTML-fila med XSLT ----------

        opf_path = temp_epub.opf_path()
        if not opf_path:
            self.utils.report.error(self.book["name"] + ": Klarte ikke å finne OPF-fila i EPUBen.")
            self.utils.report.title = self.title + ": " + self.book["name"] + " feilet 😭👎"
            return
        opf_path = os.path.join(temp_epubdir, opf_path)
        opf_xml = ElementTree.parse(opf_path).getroot()

        html_file = opf_xml.xpath("/*/*[local-name()='manifest']/*[@id = /*/*[local-name()='spine']/*[1]/@idref]/@href")
        html_file = html_file[0] if html_file else None
        if not html_file:
            self.utils.report.error(self.book["name"] + ": Klarte ikke å finne HTML-fila i OPFen.")
            self.utils.report.title = self.title + ": " + self.book["name"] + " feilet 😭👎"
            return
        html_file = os.path.join(os.path.dirname(opf_path), html_file)
        if not os.path.isfile(html_file):
            self.utils.report.error(self.book["name"] + ": Klarte ikke å finne HTML-fila.")
            self.utils.report.title = self.title + ": " + self.book["name"] + " feilet 😭👎"
            return

        temp_html_obj = tempfile.NamedTemporaryFile()
        temp_html = temp_html_obj.name

        xslt = Xslt(self, stylesheet=os.path.join(NLBpubToDocx.xslt_dir, NLBpubToDocx.uid, "prepare-for-html.xsl"),
                          source=html_file,
                          target=temp_html)
        if not xslt.success:
            self.utils.report.title = self.title + ": " + epub.identifier() + " feilet 😭👎"
            return

        docx_dir = os.path.dirname(opf_path)

        os.remove(html_file)

        # ---------- hent nytt boknummer fra /html/head/meta[@name='dc:identifier'] og bruk som filnavn ----------

        html_xml = ElementTree.parse(temp_html).getroot()
        result_identifier = html_xml.xpath("/*/*[local-name()='head']/*[@name='dc:identifier']")
        result_identifier = result_identifier[0].attrib["content"] if result_identifier and "content" in result_identifier[0].attrib else None
        if not result_identifier:
            self.utils.report.error(self.book["name"] + ": Klarte ikke å finne boknummer i ny HTML-fil.")
            self.utils.report.title = self.title + ": " + self.book["name"] + " feilet 😭👎"
            return

        html_file = os.path.join(os.path.dirname(html_file), result_identifier + ".html") # html vs xhtml ?
        shutil.copy(temp_html, html_file)
        # TODO: sett inn HTML5 doctype: <!DOCTYPE html>

        shutil.copy(os.path.join(NLBpubToDocx.xslt_dir, NLBpubToDocx.uid, "NLB_logo.jpg"),
                    os.path.join(docx_dir, "NLB_logo.jpg"))

        shutil.copy(os.path.join(NLBpubToDocx.xslt_dir, NLBpubToDocx.uid, "default.css"),
                    os.path.join(docx_dir, "default.css"))

        # ---------- slett EPUB-spesifikke filer ----------

        items = opf_xml.xpath("/*/*[local-name()='manifest']/*")
        for item in items:
            delete = False

            if "properties" in item.attrib and "nav" in re.split(r'\s+', item.attrib["properties"]):
                delete = True

            if "media-type" in item.attrib:
                if item.attrib["media-type"].startswith("audio/"):
                    delete = True
                elif item.attrib["media-type"] == "application/smil+xml":
                    delete = True

            if not delete or not "href" in item.attrib:
                continue

            fullpath = os.path.join(os.path.dirname(opf_path), item.attrib["href"])
            os.remove(fullpath)
        os.remove(opf_path)

        #print("DETTE ER DIR " +docx_dir)
        #DETTE ER DIR /tmp/tmpzzgzwu2y/EPUB

        #print("DETTE ER FIL " +html_file)
        #DETTE ER FIL /tmp/tmpzzgzwu2y/EPUB/558294092018.html
        #print(os.path.join("/tmp/book-archive/distribusjonsformater/docx/",result_identifier,result_identifier + ".docx"))

        pathlib.Path(os.path.join("/tmp/book-archive/distribusjonsformater/docx/",result_identifier)).mkdir(parents=True, exist_ok=True)

        try:
            self.utils.report.info("Konverterer fra XHTML til DOCX...")
            print(os.path.join("/tmp/book-archive/master/NLBPUB",result_identifier,"EPUB",result_identifier+".xhtml"))
            process = self.utils.filesystem.run(["/usr/bin/ebook-convert", os.path.join("/tmp/book-archive/master/NLBPUB",result_identifier,"EPUB",result_identifier+".xhtml"), os.path.join("/tmp/book-archive/distribusjonsformater/docx/",result_identifier,result_identifier + ".docx")])

            #os.path.join(docx_dir,html_file)
            #os.path.join("/tmp/book-archive/master/NLBPUB",result_identifier,"epub",result_identifier+".xhtml")

            self.utils.report.info("Boken ble konvertert. Kopierer til DOCX-arkiv.")
            #"/tmp/book-archive/distribusjonsformater/docx/123.docx"])
            #(os.path.join("/tmp/book-archive/distribusjonsformater/docx/",result_identifier + ".docx")
        except subprocess.TimeoutExpired as e:
            self.utils.report.warn("Det tok for lang tid å konvertere " + epub.identifier() + " til DOCX, og Calibre-prosessen ble derfor stoppet.")

        except Exception:
            logging.exception("En feil oppstod ved konvertering til DOCX for " + epub.identifier())
            self.utils.report.warn("En feil oppstod ved konvertering til DOCX for " + epub.identifier())
        # ---------- lagre HTML-filsett ----------

        self.utils.report.info("Boken ble konvertert. Kopierer til DOCX-arkiv.")

        #archived_path = self.utils.filesystem.storeBook(docx_dir, result_identifier)
        #self.utils.report.attachment(None, archived_path, "DEBUG")
        #self.utils.report.info(epub.identifier() + " ble lagt til i DOCX-arkivet.")
        #self.utils.report.title = self.title + ": " + epub.identifier() + " ble konvertert 👍😄"


if __name__ == "__main__":
    NLBpubToDocx().run()
