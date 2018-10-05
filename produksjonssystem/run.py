#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime
import logging
import os
import sys
import threading
import time
import traceback
from collections import OrderedDict
from email.headerregistry import Address
from threading import Thread

import yaml

from core.config import Config
from core.pipeline import DummyPipeline, Pipeline
from core.plotter import Plotter
from core.utils.slack import Slack

# Import pipelines
from check_pef import CheckPef
from epub_to_dtbook_audio import EpubToDtbookAudio
from epub_to_dtbook_braille import EpubToDtbookBraille
from epub_to_dtbook_html import EpubToDtbookHTML
from html_to_dtbook import HtmlToDtbook
from incoming_NLBPUB import (NLBPUB_incoming_validator,
                             NLBPUB_incoming_warning, NLBPUB_validator)
from incoming_nordic import IncomingNordic
from insert_metadata import (InsertMetadataBraille, InsertMetadataDaisy202,
                             InsertMetadataXhtml)
from make_abstracts import Audio_Abstract
from nlbpub_previous import NlbpubPrevious
from nlbpub_to_docx import NLBpubToDocx
from nlbpub_to_html import NlbpubToHtml
from nlbpub_to_narration_epub import NlbpubToNarrationEpub
from nlbpub_to_pef import NlbpubToPef
from nordic_dtbook_to_epub import NordicDTBookToEpub
from nordic_to_nlbpub import NordicToNlbpub
from prepare_for_braille import PrepareForBraille
from prepare_for_docx import PrepareForDocx
from prepare_for_ebook import PrepareForEbook
from update_metadata import UpdateMetadata

if sys.version_info[0] != 3 or sys.version_info[1] < 5:
    print("# This script requires Python version 3.5+")
    sys.exit(1)


class Produksjonssystem():

    book_archive_dirs = None
    email = None
    dirs = None
    pipelines = None
    environment = None
    emailDoc = []

    def __init__(self, environment=None):
        logging.basicConfig(stream=sys.stdout,
                            level=logging.DEBUG if os.environ.get("DEBUG", "1") == "1" else logging.INFO,
                            format="%(asctime)s %(levelname)-8s [%(threadName)-30s] %(message)s")

        # Set environment variables (mainly useful when testing)
        if environment:
            assert isinstance(environment, dict)
            for name in environment:
                os.environ[name] = environment[name]
            self.environment = environment
        else:
            self.environment = {}
        Pipeline.environment = self.environment  # Make environment available from pipelines
        # Check that archive dirs is defined
        assert os.environ.get("BOOK_ARCHIVE_DIRS"), (
            "The book archives must be defined as a space separated list in the environment variable BOOK_ARCHIVE_DIRS (as name=path pairs)")
        self.book_archive_dirs = {}
        for d in os.environ.get("BOOK_ARCHIVE_DIRS").split(" "):
            assert "=" in d, "Book archives must be specified as name=path. For instance: master=/media/archive. Note that paths can not contain spaces."
            archive_name = d.split("=")[0]
            archive_path = os.path.normpath(d.split("=")[1]) + "/"
            self.book_archive_dirs[archive_name] = archive_path

        # for convenience; both method variable and instance variable so you don't have to
        # write "self." all the time during initialization.
        book_archive_dirs = self.book_archive_dirs

        # Configure email
        self.email = {
            "smtp": {},
            "sender": Address("NLBs Produksjonssystem", "produksjonssystem", "nlb.no")
        }
        if os.environ.get("MAIL_SERVER", None):
            self.email["smtp"]["host"] = os.environ.get("MAIL_SERVER", None)
        if os.environ.get("MAIL_PORT", None):
            self.email["smtp"]["port"] = os.environ.get("MAIL_PORT", None)
        if os.environ.get("MAIL_USERNAME", None):
            self.email["smtp"]["user"] = os.environ.get("MAIL_USERNAME", None)
        if os.environ.get("MAIL_PASSWORD", None):
            self.email["smtp"]["pass"] = os.environ.get("MAIL_PASSWORD", None)

        # Special directories
        Config.set("master_dir", os.path.join(book_archive_dirs["master"], "master/EPUB"))
        Config.set("reports_dir", os.getenv("REPORTS_DIR", os.path.join(book_archive_dirs["master"], "rapporter")))
        Config.set("metadata_dir", os.getenv("METADATA_DIR", os.path.join(book_archive_dirs["master"], "metadata")))

        # Define directories (using OrderedDicts to preserve order when plotting)
        self.dirs_ranked = []

        self.dirs_ranked.append({
            "id": "incoming",
            "name": "Mottak",
            "dirs": OrderedDict()
        })
        self.dirs_ranked[-1]["dirs"]["incoming_NLBPUB"] = os.path.join(book_archive_dirs["master"], "innkommende/NLBPUB")
        self.dirs_ranked[-1]["dirs"]["nlbpub_manuell"] = os.path.join(book_archive_dirs["master"], "mottakskontroll/NLBPUB")
        self.dirs_ranked[-1]["dirs"]["incoming"] = os.path.join(book_archive_dirs["master"], "innkommende/nordisk")

        self.dirs_ranked.append({
            "id": "source-in",
            "name": "Ubehandlet kildefil",
            "dirs": OrderedDict()
        })

        self.dirs_ranked.append({
            "id": "source-out",
            "name": "Behandlet kildefil",
            "dirs": OrderedDict()
        })

        self.dirs_ranked.append({
            "id": "master",
            "name": "Grunnlagsfil",
            "dirs": OrderedDict()
        })
        self.dirs_ranked[-1]["dirs"]["master"] = Config.get("master_dir")
        self.dirs_ranked[-1]["dirs"]["metadata"] = Config.get("metadata_dir")
        self.dirs_ranked[-1]["dirs"]["grunnlag"] = os.path.join(book_archive_dirs["master"], "grunnlagsfil/NLBPUB")
        self.dirs_ranked[-1]["dirs"]["nlbpub"] = os.path.join(book_archive_dirs["master"], "master/NLBPUB")
        self.dirs_ranked[-1]["dirs"]["old_dtbook"] = os.path.join(book_archive_dirs["master"], "grunnlagsfil/DTBook")
        self.dirs_ranked[-1]["dirs"]["epub_from_dtbook"] = os.path.join(book_archive_dirs["master"], "grunnlagsfil/EPUB-fra-DTBook")

        self.dirs_ranked.append({
            "id": "version-control",
            "name": "Versjonskontroll",
            "dirs": OrderedDict()
        })
        self.dirs_ranked[-1]["dirs"]["nlbpub-previous"] = os.path.join(book_archive_dirs["master"], "master/NLBPUB-tidligere")

        self.dirs_ranked.append({
                "id": "publication-in",
                "name": "Format-spesifikk metadata",
                "dirs": OrderedDict()
        })
        self.dirs_ranked[-1]["dirs"]["pub-in-epub"] = os.path.join(book_archive_dirs["master"], "utgave-inn/EPUB")
        self.dirs_ranked[-1]["dirs"]["pub-in-braille"] = os.path.join(book_archive_dirs["master"], "utgave-inn/punktskrift")
        self.dirs_ranked[-1]["dirs"]["pub-in-ebook"] = os.path.join(book_archive_dirs["master"], "utgave-inn/e-tekst")
        self.dirs_ranked[-1]["dirs"]["pub-in-audio"] = os.path.join(book_archive_dirs["master"], "utgave-inn/lydbok")

        self.dirs_ranked.append({
            "id": "publication-ready",
            "name": "Klar for produksjon",
            "dirs": OrderedDict()
        })
        self.dirs_ranked[-1]["dirs"]["dtbook"] = os.path.join(book_archive_dirs["master"], "utgave-klargjort/DTBook")
        self.dirs_ranked[-1]["dirs"]["pub-ready-braille"] = os.path.join(book_archive_dirs["master"], "utgave-klargjort/punktskrift")
        self.dirs_ranked[-1]["dirs"]["pub-ready-ebook"] = os.path.join(book_archive_dirs["master"], "utgave-klargjort/e-bok")
        self.dirs_ranked[-1]["dirs"]["pub-ready-docx"] = os.path.join(book_archive_dirs["master"], "utgave-klargjort/DOCX")
        self.dirs_ranked[-1]["dirs"]["epub_narration"] = os.path.join(book_archive_dirs["master"], "utgave-klargjort/EPUB-til-innlesing")
        self.dirs_ranked[-1]["dirs"]["dtbook_tts"] = os.path.join(book_archive_dirs["master"], "utgave-klargjort/DTBook-til-talesyntese")
        self.dirs_ranked[-1]["dirs"]["dtbook_html"] = os.path.join(book_archive_dirs["master"], "utgave-klargjort/DTBook-til-HTML")
        self.dirs_ranked[-1]["dirs"]["dtbook_braille"] = os.path.join(book_archive_dirs["master"], "utgave-klargjort/DTBook-punktskrift")

        self.dirs_ranked.append({
            "id": "publication-out",
            "name": "Ferdig produsert",
            "dirs": OrderedDict()
        })
        self.dirs_ranked[-1]["dirs"]["pef"] = os.path.join(book_archive_dirs["master"], "utgave-ut/PEF")
        self.dirs_ranked[-1]["dirs"]["html"] = os.path.join(book_archive_dirs["master"], "utgave-ut/HTML")
        self.dirs_ranked[-1]["dirs"]["docx"] = os.path.join(book_archive_dirs["master"], "utgave-ut/DOCX")
        self.dirs_ranked[-1]["dirs"]["daisy202"] = os.path.join(book_archive_dirs["share"], "daisy202")

        self.dirs_ranked.append({
            "id": "distribution",
            "name": "Klar til distribusjon",
            "dirs": OrderedDict()
        })
        self.dirs_ranked[-1]["dirs"]["abstracts"] = os.path.join(book_archive_dirs["distribution"], "www/abstracts")
        self.dirs_ranked[-1]["dirs"]["pef-checked"] = os.path.join(book_archive_dirs["master"], "utgave-ut/PEF-kontrollert")

        # also make dirs available from static contexts
        Pipeline.dirs_ranked = self.dirs_ranked

        # Make a key/value version of dirs_ranked for convenience
        self.dirs = {
            "reports": Config.get("reports_dir")
        }
        for rank in self.dirs_ranked:
            for dir in rank["dirs"]:
                self.dirs[dir] = rank["dirs"][dir]

        # Define pipelines and input/output/report dirs
        self.pipelines = [
            # Konvertering av gamle DTBøker til EPUB 3
            [NordicDTBookToEpub(retry_missing=True),              "old_dtbook",     "epub_from_dtbook"],

            # Mottak, nordic guidelines 2015-1
            [NLBPUB_incoming_validator(retry_all=True),       "incoming_NLBPUB",     "grunnlag"],
            [NLBPUB_incoming_warning(retry_all=True),         "incoming_NLBPUB",     "nlbpub_manuell"],
            [DummyPipeline("Manuell sjekk av NLBPUB",
                           labels=["EPUB"]),                  "nlbpub_manuell",      "grunnlag"],
            # [NLBPUB_validator(overwrite=False),                              "grunnlag",            "nlbpub"],
            [IncomingNordic(retry_all=True),                  "incoming",            "master"],
            [NordicToNlbpub(retry_missing=True, overwrite=False),              "master",              "nlbpub"],

            # Grunnlagsfiler
            [NlbpubPrevious(retry_missing=True),              "nlbpub",              "nlbpub-previous"],
            [UpdateMetadata(),                                "metadata",            "nlbpub"],
            [HtmlToDtbook(),                                  "nlbpub",              "dtbook"],

            # EPUB
            # [InsertMetadataEpub(),                            "nlbpub",              "pub-in-epub"],

            # e-bok
            [InsertMetadataXhtml(),                           "nlbpub",              "pub-in-ebook"],
            [PrepareForEbook(retry_missing=True),             "pub-in-ebook",        "pub-ready-ebook"],
            [PrepareForDocx(retry_missing=True),              "pub-in-ebook",        "pub-ready-docx"],
            [NlbpubToHtml(retry_missing=True),                "pub-ready-ebook",     "html"],
            [NLBpubToDocx(retry_missing=True),                "pub-ready-docx",      "docx"],

            # punktskrift
            [InsertMetadataBraille(),                         "nlbpub",              "pub-in-braille"],
            [PrepareForBraille(retry_missing=True),           "pub-in-braille",      "pub-ready-braille"],
            [NlbpubToPef(retry_missing=True),                 "pub-ready-braille",   "pef"],
            [CheckPef(),                                      "pef",                 "pef-checked"],

            # innlest lydbok
            [InsertMetadataDaisy202(),                        "nlbpub",              "pub-in-audio"],
            [NlbpubToNarrationEpub(retry_missing=True),       "pub-in-audio",        "epub_narration"],
            [DummyPipeline("Innlesing med Hindenburg",
                           labels=["Lydbok"]),                "epub_narration",      "daisy202"],

            # TTS-lydbok
            [EpubToDtbookAudio(),                             "master",              "dtbook_tts"],
            [DummyPipeline("Talesyntese i Pipeline 1",
                           labels=["Lydbok"]),                "dtbook_tts",          "daisy202"],

            # e-bok basert på DTBook
            [EpubToDtbookHTML(),                              "master",              "dtbook_html"],
            [DummyPipeline("Pipeline 1 og Ammars skript",
                           labels=["e-bok"]),                 "dtbook_html",         None],

            # DTBook for punktskrift
            [EpubToDtbookBraille(),                           "master",              "dtbook_braille"],
            [DummyPipeline("Punktskrift med NorBraille",
                           labels=["Punktskrift"]),           "dtbook_braille",      None],

            # lydutdrag
            [Audio_Abstract(retry_missing=True),              "daisy202",            "abstracts"],
        ]

    # ---------------------------------------------------------------------------
    # Don't edit below this line if you only want to add/remove/modify a pipeline
    # ---------------------------------------------------------------------------

    def info(self, text):
        logging.info(text)
        Slack.slack(text, None)

    def run(self, debug=False):
        try:
            if debug:
                logging.getLogger().setLevel(logging.DEBUG)
            else:
                logging.getLogger().setLevel(logging.INFO)
            self.info("Starter produksjonssystemet...")
            self._run()
        except Exception as e:
            self.info("En feil oppstod i produksjonssystemet: {}".format(str(e) if str(e) else "(ukjent)"))
            logging.exception("En feil oppstod i produksjonssystemet")
        finally:
            self.info("Produksjonssystemet er stoppet")

    def _run(self):
        assert os.getenv("CONFIG_FILE"), "CONFIG_FILE must be defined"

        # Make sure that directories are defined properly
        for d in self.book_archive_dirs:
            for a in self.book_archive_dirs:
                if d == a:
                    continue
                d_norm = os.path.normpath(self.book_archive_dirs[d]) + "/"
                a_norm = os.path.normpath(self.book_archive_dirs[a]) + "/"
                assert not (a != d and a_norm == d_norm), "Two book archives must not be equal ({} == {})".format(
                    self.book_archive_dirs[a], self.book_archive_dirs[d])
                assert not (a != d and a_norm.startswith(d_norm) or d_norm.startswith(a_norm)), (
                    "Book archives can not contain eachother ({} contains or is contained by {})".format(self.book_archive_dirs[a], self.book_archive_dirs[d]))
        for d in self.dirs:
            self.dirs[d] = os.path.normpath(self.dirs[d])
        for d in self.dirs:
            if not d == "reports":
                assert [a for a in self.book_archive_dirs if self.dirs[d].startswith(self.book_archive_dirs[a])], (
                    "Directory \"" + d + "\" must be part of one of the book archives: " + self.dirs[d])
            assert not [a for a in self.book_archive_dirs if os.path.normpath(self.dirs[d]) == os.path.normpath(self.book_archive_dirs[a])], (
                "The directory \"" + d + "\" must not be equal to any of the book archive dirs: " + self.dirs[d])
            assert len([x for x in self.dirs if self.dirs[x] == self.dirs[d]]), "The directory \"" + d + "\" is defined multiple times: " + self.dirs[d]

        # Make sure that the pipelines are defined properly
        for pipeline in self.pipelines:
            assert len(pipeline) == 3, "Pipeline declarations have three arguments (not " + len(pipeline) + ")"
            assert isinstance(pipeline[0], Pipeline), "The first argument of a pipeline declaration must be a pipeline instance"
            assert pipeline[1] is None or isinstance(pipeline[1], str), "The second argument of a pipeline declaration must be a string or None"
            assert pipeline[2] is None or isinstance(pipeline[2], str), "The third argument of a pipeline declaration must be a string or None"
            assert pipeline[1] is None or pipeline[1] in self.dirs, (
                "The second argument of a pipeline declaration (\"" + str(pipeline[1]) + "\") must be None or refer to a key in \"dirs\"")
            assert pipeline[2] is None or pipeline[2] in self.dirs, (
                "The third argument of a pipeline declaration (\"" + str(pipeline[2]) + "\") must be None or refer to a key in \"dirs\"")

        # Some useful output to stdout before starting everything else
        print("")
        print("Dashboard: file://" + os.path.join(Config.get("reports_dir"), "dashboard.html"))
        for d in self.book_archive_dirs:
            print("Book archive \"{}\": file://{}".format(d, self.book_archive_dirs[d]))
        print("")

        # Make directories
        for d in self.dirs:
            os.makedirs(self.dirs[d], exist_ok=True)

        threads = []
        file_name = os.environ.get("CONFIG_FILE")
        self.emailDoc = ""
        with open(file_name, 'r') as f:
                try:
                    self.emailDoc = yaml.load(f)
                except Exception as e:
                    self.info("En feil oppstod under lasting av konfigurasjonsfilen. Sjekk syntaksen til produksjonssystem.yaml")
                    traceback.print_exc(e)

        # Make pipelines available from static methods in the Pipeline class
        Pipeline.pipelines = [pipeline[0] for pipeline in self.pipelines]

        for common in self.emailDoc["common"]:
            for common_key in common:
                Config.set(common_key, common[common_key])

        for pipeline in self.pipelines:
            email_settings = {
                "smtp": self.email["smtp"],
                "sender": self.email["sender"],
                "recipients": []
            }
            pipeline_config = {}
            if pipeline[0].uid in self.emailDoc:
                for recipient in self.emailDoc[pipeline[0].uid]:
                    if isinstance(recipient, str):
                        email_settings["recipients"].append(recipient)
                    elif isinstance(recipient, dict):
                        for key in recipient:
                            pipeline_config[key] = recipient[key]

            thread = Thread(target=pipeline[0].run, name=pipeline[0].uid,
                            args=(10,
                                  self.dirs[pipeline[1]] if pipeline[1] else None,
                                  self.dirs[pipeline[2]] if pipeline[2] else None,
                                  self.dirs["reports"],
                                  email_settings,
                                  self.book_archive_dirs,
                                  pipeline_config
                                  ))

            thread.setDaemon(True)
            thread.start()
            threads.append(thread)

        self.shouldRun = True
        self._configThread = Thread(target=self._config_thread, name="config")
        self._configThread.setDaemon(True)
        self._configThread.start()

        self._dailyReportThread = Thread(target=self._daily_report_thread, name="daily report")
        self._dailyReportThread.setDaemon(True)
        self._dailyReportThread.start()

        plotter = Plotter(self.pipelines, report_dir=self.dirs["reports"])
        graph_thread = Thread(target=plotter.run, name="graph")
        graph_thread.setDaemon(True)
        graph_thread.start()

        self.info("Produksjonssystemet er startet")

        try:
            stopfile = os.getenv("TRIGGER_DIR")
            if stopfile:
                stopfile = os.path.join(stopfile, "stop")

            running = True
            while running:
                time.sleep(1)

                if os.path.exists(stopfile):
                    self.info("Sender stoppsignal til alle pipelines...")
                    os.remove(stopfile)
                    for pipeline in self.pipelines:
                        pipeline[0].stop(exit=True)

                if os.getenv("STOP_AFTER_FIRST_JOB", False):
                    running = 0
                    for pipeline in self.pipelines:
                        if pipeline[0].running:
                            running += 1
                    running = True if running > 0 else False
                else:
                    for thread in threads:
                        if not thread.isAlive():
                            running = False
                            break
        except KeyboardInterrupt:
            pass

        for pipeline in self.pipelines:
            pipeline[0].stop(exit=True)

        self.info("Venter på at alle pipelinene skal stoppe...")
        for thread in threads:
            if thread:
                logging.debug("joining {}".format(thread.name))
            thread.join(timeout=5)

        is_alive = True
        while is_alive:
            is_alive = False
            for thread in threads:
                if thread and thread != threading.current_thread() and thread.is_alive():
                    is_alive = True
                    logging.info("Thread is still running: {}".format(thread.name))
                    thread.join(timeout=5)
            for pipeline in self.pipelines:
                if pipeline[0].running:
                    self.info("{} kjører fortsatt, venter på at den skal stoppe{}...".format(
                        pipeline[0].title,
                        " ({} / {})".format(pipeline[0].book["name"], pipeline[0].get_progress()) if pipeline[0].book else ""))

        self.info("Venter på at plotteren skal stoppe...")
        time.sleep(5)  # gi plotteren litt tid på slutten
        plotter.should_run = False
        if graph_thread:
            logging.debug("joining {}".format(graph_thread.name))
        graph_thread.join()
        if graph_thread:
            logging.debug("joined {}".format(graph_thread.name))

        self.info("Venter på at konfigtråden skal stoppe...")
        self.shouldRun = False
        self._configThread.join()
        self.info("Venter på at dagsrapport tråden skal stoppe...")
        self._dailyReportThread

    def wait_until_running(self, timeout=60):
        start_time = time.time()

        while time.time() - start_time < timeout:
            waiting = 0
            for pipeline in self.pipelines:
                if pipeline[0]._shouldRun and not pipeline[0].running:
                    waiting += 1
            if waiting == 0:
                return True

        return False

    def stop(self):
        stopfile = os.getenv("TRIGGER_DIR")
        assert stopfile, "TRIGGER_DIR must be defined"
        stopfile = os.path.join(stopfile, "stop")
        with open(stopfile, "w") as f:
            f.write("stop")

    def _daily_report_thread(self):
        mail_sent_today = False
        yesterday = datetime.datetime.now() - datetime.timedelta(1)
        yesterday = str(yesterday.strftime("%Y-%m-%d"))
        daily_dir = os.path.join(self.dirs["reports"], "logs", "dagsrapporter", yesterday)

        while self.shouldRun:
            time.sleep(5)
            if 2 <= datetime.datetime.now().hour <= 3 and mail_sent_today is True:
                mail_sent_today = False

            if not (7 <= datetime.datetime.now().hour <= 8) or mail_sent_today is True:
                continue
            else:
                for pipeline in self.pipelines:
                    try:
                        if "dummy" not in pipeline[0].uid:
                            number_produced = 0
                            number_failed = 0
                            file = os.path.join(daily_dir, pipeline[0].uid)
                            message = "<h1>Produsert i pipeline: " + pipeline[0].title + ": " + yesterday + "</h1>\n"
                            message = message + "\n<h2>Bøker som har gått gjennom:</h2>"
                            report_content = ""
                            dirs = [pipeline[0].dir_out, pipeline[0].dir_in]
                            dir_log = self.dirs["reports"]
                            logfile = os.path.join(pipeline[0].uid, "log.txt")
                            if (os.path.isfile(file + "-SUCCESS.txt")):
                                with open(file + "-SUCCESS.txt", "r") as report_file_success:
                                    report_content = report_file_success.readlines()
                                    message = message + self.format_email_report(report_content, dirs, dir_log, logfile, self.book_archive_dirs["master"])
                                    for line in report_content:
                                        if pipeline[0].title in line and line.startswith("["):
                                            number_produced += 1
                            else:
                                message = message + "\nIngen ble produsert\n"

                            message = message + "\n<h2>Bøker som har mislyktes:</h2>"
                            if (os.path.isfile(file + "-FAIL.txt")):
                                with open(file + "-FAIL.txt", "r") as report_file_fail:
                                    report_content = report_file_fail.readlines()
                                    message = message + self.format_email_report(report_content, dirs, dir_log, logfile, self.book_archive_dirs["master"])
                                    for line in report_content:
                                        if pipeline[0].title in line and line.startswith("["):
                                            number_failed += 1
                            else:
                                message = message + "\nIngen feilet\n"
                            message = message + "\n<h2>Totalt ble {} produsert og {} feilet</h2>\n".format(number_produced, number_failed)
                            pipeline[0].daily_report(message)
                    except Exception:
                        self.info("En feil oppstod under sending av dagsrapporten for " + pipeline[0].title)
                        self.info(traceback.format_exc())
                mail_sent_today = True

    def _config_thread(self):
        fileName = os.environ.get("CONFIG_FILE")
        last_update = 0
        while(self.shouldRun):

            if time.time() - last_update < 300:
                time.sleep(5)
                continue
            last_update = time.time()

            try:
                with open(fileName, 'r') as f:
                    tempEmailDoc = yaml.load(f)
                if tempEmailDoc != self.emailDoc:
                    self.info("Oppdaterer konfig fra fil")

                    try:
                        for tempkey in tempEmailDoc:
                            changes = self.find_diff(tempEmailDoc, self.emailDoc, tempkey)
                            if not changes == "":
                                self.info(changes)
                    except Exception:
                        pass

                    self.emailDoc = tempEmailDoc

                    for common in self.emailDoc["common"]:
                        for common_key in common:
                            Config.set(common_key, common[common_key])

                    for pipeline in self.pipelines:
                        if not pipeline[0].running:
                            continue

                        recipients = []
                        pipeline_config = {}

                        if pipeline[0].uid in self.emailDoc and self.emailDoc[pipeline[0].uid]:
                            for recipient in self.emailDoc[pipeline[0].uid]:
                                if isinstance(recipient, str):
                                    recipients.append(recipient)
                                elif isinstance(recipient, dict):
                                    for key in recipient:
                                        pipeline_config[key] = recipient[key]

                        pipeline[0].email_settings["recipients"] = recipients
                        pipeline[0].config = pipeline_config

            except Exception:
                self.info("En feil oppstod under lasting av konfigurasjonsfil. Sjekk syntaksen til" + fileName)
                self.info(traceback.format_exc())

    def find_diff(self, new_config, old_config, tempkey):
        for key_in_config in new_config[tempkey]:
            if isinstance(key_in_config, str):

                if len(new_config[tempkey]) > len(old_config[tempkey]):
                    delta = (yaml.dump(list(set(new_config[tempkey])-set(old_config[tempkey])), default_flow_style=False))
                    return ("Følgende mottakere ble lagt til i {} : \n{}" .format(tempkey, delta))

                if len(new_config[tempkey]) < len(old_config[tempkey]):
                    delta = (yaml.dump(list(set(old_config[tempkey])-set(new_config[tempkey])), default_flow_style=False))
                    return ("Følgende mottakere ble fjernet i {} : \n{}" .format(tempkey, delta))

            elif isinstance(key_in_config, dict):
                for i in range(0, len(new_config[tempkey])):
                    if isinstance(new_config[tempkey][i], dict):

                        for item in new_config[tempkey][i]:
                            tempset_new = set(new_config[tempkey][i][item])
                            tempset_old = set(old_config[tempkey][i][item])

                            if (len(tempset_new) > len(tempset_old)):
                                delta = (yaml.dump(list(tempset_new-tempset_old), default_flow_style=False))
                                return ("Følgende mottakere ble lagt til i {}: {} : \n{}" .format(tempkey, item, delta))

                            elif (len(tempset_new) < len(tempset_old)):
                                delta = (yaml.dump(list(tempset_old-tempset_new), default_flow_style=False))
                                return ("Følgende mottakere ble fjernet i {}: {} : \n{}" .format(tempkey, item, delta))
        return ""

    @staticmethod
    def format_email_report(content, dirs, dir_log, logfile, book_archive):
        message = ""
        log_path = ""
        first_dir_log = True
        for line in content:
            if "(li)" in line:
                line = line.replace("(li)", "")
                message = message + "\n<ul>\n<li>" + line + "</li>\n</ul>"
            elif "(href)" in line:
                line = line.replace("(href)", "")
                for dir in dirs:
                    if dir in line or dir in line.replace("\\", "/"):
                        short_path = line.replace(os.path.basename(dir), "")
                        message = message + "\n<ul>\n<li><a href=\"file:///{}\">{}</a></li>\n</ul>".format(line, short_path)
                if logfile in line or logfile in line.replace("\\", "/"):
                    if first_dir_log:
                        log_path = os.path.dirname(line)
                        short_path = log_path.replace(book_archive, "")
                        message = message + "\n<ul>\n<li><a href=\"file:///{}\">{}</a></li>\n</ul>".format(log_path, short_path)
                        first_dir_log = False
            elif line != "":
                first_dir_log = True
                if "mail:" in line:
                    splitline = line.split("mail: ")
                    message = message + "\n<b>{}<a href=\"file:///{}\">Link</a></b>".format(splitline[0], splitline[-1])
                    continue
                message = message + "\n" + "<b>" + line + "</b>"
        return message


if __name__ == "__main__":
    threading.current_thread().setName("main thread")
    debug = "debug" in sys.argv
    produksjonssystem = Produksjonssystem()
    produksjonssystem.run(debug=debug)
