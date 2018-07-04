#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shutil
import tempfile

from lxml import etree as ElementTree
from core.utils.epub import Epub
from core.utils.xslt import Xslt
from core.utils.daisy_pipeline import DaisyPipelineJob

from core.pipeline import Pipeline

if sys.version_info[0] != 3 or sys.version_info[1] < 5:
    print("# This script requires Python version 3.5+")
    sys.exit(1)


class NordicToNlbpub(Pipeline):
    uid = "nordic-epub-to-nlbpub"
    title = "Nordisk EPUB til NLBPUB"
    labels = ["EPUB", "Lydbok", "Innlesing", "Talesyntese", "Punktskrift", "e-bok"]
    publication_format = None
    expected_processing_time = 686

    xslt_dir = os.path.realpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "xslt"))

    def on_book_deleted(self):
        self.utils.report.info("Slettet bok i mappa: " + self.book['name'])
        self.utils.report.title = self.title + " EPUB master slettet: " + self.book['name']
        return True

    def on_book_modified(self):
        self.utils.report.info("Endret bok i mappa: " + self.book['name'])
        return self.on_book()

    def on_book_created(self):
        self.utils.report.info("Ny bok i mappa: " + self.book['name'])
        return self.on_book()

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
            return False

        if not epub.identifier():
            self.utils.report.error(self.book["name"] + ": Klarte ikke å bestemme boknummer basert på dc:identifier.")
            self.utils.report.title = self.title + ": " + self.book["name"] + " feilet 😭👎"
            return False

        temp_html_file_obj = tempfile.NamedTemporaryFile()
        temp_html_file = temp_html_file_obj.name

        temp_opf_file_obj = tempfile.NamedTemporaryFile()
        temp_opf_file = temp_opf_file_obj.name

        self.utils.report.info("Lager en kopi av EPUBen")
        temp_epubdir_obj = tempfile.TemporaryDirectory()
        temp_epubdir = temp_epubdir_obj.name
        self.utils.filesystem.copy(self.book["source"], temp_epubdir)
        temp_epub = Epub(self, temp_epubdir)

        self.utils.report.info("Rydder opp i nordisk EPUB")
        nav_path = temp_epub.nav_path()
        for root, dirs, files in os.walk(temp_epubdir):
            for f in files:
                file = os.path.join(root, f)
                if not file.endswith(".xhtml"):
                    continue
                if file == nav_path:
                    continue

                xslt = Xslt(self,
                            stylesheet=os.path.join(NordicToNlbpub.xslt_dir, NordicToNlbpub.uid, "nordic-cleanup-epub.xsl"),
                            source=file,
                            target=temp_html_file)
                if not xslt.success:
                    self.utils.report.title = self.title + ": " + epub.identifier() + " feilet 😭👎" + epubTitle
                    return False
                shutil.copy(temp_html_file, file)

        xslt = Xslt(self,
                    stylesheet=os.path.join(NordicToNlbpub.xslt_dir, NordicToNlbpub.uid, "nordic-cleanup-opf.xsl"),
                    source=os.path.join(temp_epubdir, temp_epub.opf_path()),
                    target=temp_opf_file)
        if not xslt.success:
            self.utils.report.title = self.title + ": " + epub.identifier() + " feilet 😭👎" + epubTitle
            return False
        shutil.copy(temp_opf_file, os.path.join(temp_epubdir, temp_epub.opf_path()))
        temp_epub.refresh_metadata()

        html_dir_obj = tempfile.TemporaryDirectory()
        html_dir = html_dir_obj.name
        html_file = os.path.join(html_dir, epub.identifier() + ".xhtml")

        self.utils.report.info("Zipper oppdatert versjon av EPUBen...")
        temp_epub.asFile(rebuild=True)

        self.utils.report.info("Validerer Nordisk EPUB 3...")
        with DaisyPipelineJob(self, "nordic-epub3-validate", {"epub": temp_epub.asFile()}) as dp2_job_epub_validate:
            epub_validate_status = None
            if dp2_job_epub_validate.status == "DONE":
                epub_validate_status = "SUCCESS"
            elif dp2_job_epub_validate.status in ["VALIDATION_FAIL", "FAIL"]:
                epub_validate_status = "WARN"
            else:
                epub_validate_status = "ERROR"

            report_file = os.path.join(dp2_job_epub_validate.dir_output, "html-report/report.xhtml")

            if epub_validate_status == "WARN":
                report_doc = ElementTree.parse(report_file)
                errors = [e.xpath('.//text()[normalize-space()]')[0] for e in report_doc.xpath('//*[@class="error"]')]
                for error in errors:
                    if (bool(error) and (
                            error.startswith("[opf") or
                            error.startswith("[nordic_nav") or
                            error.startswith("[nordic_opf"))):
                        continue  # ignorer disse feilmeldingene; de forsvinner når vi konverterer til XHTML5

                    else:
                        epub_validate_status = "ERROR"
                        self.utils.report.error(error)

            # get conversion report
            if os.path.isfile(report_file):
                with open(report_file, 'r') as result_report:
                    self.utils.report.attachment(result_report.readlines(),
                                                 os.path.join(self.utils.report.reportDir(), "report-epub.html"),
                                                 epub_validate_status)

            if epub_validate_status == "ERROR":
                self.utils.report.error("Klarte ikke å validere boken")
                self.utils.report.title = self.title + ": " + epub.identifier() + " feilet 😭👎" + epubTitle
                return False

            if epub_validate_status == "WARN":
                self.utils.report.warn("EPUBen er ikke valid, men vi fortsetter alikevel.")

        self.utils.report.info("Konverterer fra Nordisk EPUB 3 til Nordisk HTML 5...")
        with DaisyPipelineJob(self, "nordic-epub3-to-html", {"epub": temp_epub.asFile(), "fail-on-error": "false"}) as dp2_job_convert:
            convert_status = "SUCCESS" if dp2_job_convert.status == "DONE" else "ERROR"

            if convert_status != "SUCCESS":
                self.utils.report.error("Klarte ikke å konvertere boken")
                self.utils.report.title = self.title + ": " + epub.identifier() + " feilet 😭👎" + epubTitle
                return False

            dp2_html_dir = os.path.join(dp2_job_convert.dir_output, "output-dir", epub.identifier())
            dp2_html_file = os.path.join(dp2_job_convert.dir_output, "output-dir", epub.identifier(), epub.identifier() + ".xhtml")

            if not os.path.isdir(dp2_html_dir):
                self.utils.report.error("Finner ikke den konverterte boken: {}".format(dp2_html_dir))
                self.utils.report.title = self.title + ": " + epub.identifier() + " feilet 😭👎" + epubTitle
                return False

            if not os.path.isfile(dp2_html_file):
                self.utils.report.error("Finner ikke den konverterte boken: {}".format(dp2_html_file))
                self.utils.report.info("Kanskje filnavnet er forskjellig fra IDen?")
                self.utils.report.title = self.title + ": " + epub.identifier() + " feilet 😭👎" + epubTitle
                return False

            self.utils.report.info("Validerer Nordisk HTML 5...")
            with DaisyPipelineJob(self, "nordic-html-validate", {"html": dp2_html_file}) as dp2_job_html_validate:
                html_validate_status = "SUCCESS" if dp2_job_html_validate.status == "DONE" else "ERROR"

                # get conversion report
                report_file = os.path.join(dp2_job_html_validate.dir_output, "html-report/report.xhtml")
                if os.path.isfile(report_file):
                    with open(report_file, 'r') as result_report:
                        self.utils.report.attachment(result_report.readlines(),
                                                     os.path.join(self.utils.report.reportDir(), "report-html.html"),
                                                     html_validate_status)

                if html_validate_status == "ERROR":
                    self.utils.report.error("Klarte ikke å validere HTML-versjonen av boken")
                    self.utils.report.title = self.title + ": " + epub.identifier() + " feilet 😭👎" + epubTitle
                    return False

            self.utils.filesystem.copy(dp2_html_dir, html_dir)

        self.utils.report.info("Rydder opp i nordisk HTML")
        xslt = Xslt(self, stylesheet=os.path.join(NordicToNlbpub.xslt_dir, NordicToNlbpub.uid, "nordic-cleanup.xsl"),
                    source=html_file,
                    target=temp_html_file)
        if not xslt.success:
            self.utils.report.title = self.title + ": " + epub.identifier() + " feilet 😭👎" + epubTitle
            return False
        shutil.copy(temp_html_file, html_file)

        self.utils.report.info("Legger til EPUB-filer (OPF, NAV, container.xml, mediatype)...")
        nlbpub_tempdir_obj = tempfile.TemporaryDirectory()
        nlbpub_tempdir = nlbpub_tempdir_obj.name

        nlbpub = Epub.from_html(self, html_dir, nlbpub_tempdir)
        if nlbpub is None:
            self.utils.report.title = self.title + ": " + epub.identifier() + " feilet 😭👎" + epubTitle
            return False

        self.utils.report.info("Boken ble konvertert. Kopierer til NLBPUB-arkiv.")
        archived_path = self.utils.filesystem.storeBook(nlbpub.asDir(), temp_epub.identifier())
        self.utils.report.attachment(None, archived_path, "DEBUG")
        self.utils.report.info(epub.identifier() + " ble lagt til i NLBPUB-arkivet.")
        self.utils.report.title = self.title + ": " + epub.identifier() + " ble konvertert 👍😄" + epubTitle
        return True


if __name__ == "__main__":
    NordicToNlbpub().run()
