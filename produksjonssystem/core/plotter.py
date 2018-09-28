#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import re
import shutil
import sys
import threading
import time

from core.pipeline import DummyPipeline, Pipeline
from core.utils.filesystem import Filesystem
from core.utils.metadata import Metadata
from graphviz import Digraph

if sys.version_info[0] != 3 or sys.version_info[1] < 5:
    print("# This script requires Python version 3.5+")
    sys.exit(1)


class Plotter():
    """
    Generates a HTML page displaying the current state of the system, for use on dashboards.
    """

    pipelines = None  # [ [pipeline,in,out,reports,[recipients,...], ...]
    report_dir = None
    buffered_network_paths = {}
    buffered_network_hosts = {}
    should_run = True
    book_count = {}
    threads = None

    debug_logging = False

    def __init__(self, pipelines, report_dir):
        self.pipelines = pipelines
        self.report_dir = report_dir

    def get_book_count(self, dir, parentdirs=None):
        if not isinstance(dir, str):
            return 0
        if dir not in self.book_count:
            self.book_count[dir] = {
                "parentdirs": parentdirs,
                "count": 0,
                "modified": 0
            }
        if parentdirs:
            self.book_count[dir]["parentdirs"] = parentdirs
        return self.book_count[dir]["count"]

    def rank_name(self, rank_id):
        for rank in Pipeline.dirs_ranked:
            if rank["id"] == rank_id:
                return rank["name"]
        return None

    def next_rank(self, rank_id):
        use_next = False
        for rank in Pipeline.dirs_ranked:
            if use_next:
                return rank["id"]
            elif rank["id"] == rank_id:
                use_next = True
        return None

    def plot(self, uids, name):
        if self.debug_logging:
            logging.info("plot(self, {}, {})".format(" ".join(uids), name))
        dot = Digraph(name="Produksjonssystem", format="png")

        node_ranks = {}
        for rank in Pipeline.dirs_ranked:
            node_ranks[rank["id"]] = []

        # remember edges so that we don't plot them twice
        edges = {}

        for pipeline in self.pipelines:
            if not pipeline[0].uid in uids:
                continue

            if self.debug_logging:
                logging.info("for pipeline in self.pipelines: (pipeline={})".format(pipeline[0].uid))
            title = pipeline[0].title if pipeline[0].title else pipeline[0].uid
            pipeline_id = re.sub(r"[^a-z\d]", "", title.lower())

            if self.debug_logging:
                logging.info("before pipeline[0].get_queue()")
            queue = pipeline[0].get_queue()
            if self.debug_logging:
                logging.info("after pipeline[0].get_queue()")

            if self.debug_logging:
                logging.info("before many invocations of Pipeline.get_main_event(book)")
            queue_created = len([book for book in queue if Pipeline.get_main_event(book) == "created"]) if queue else 0
            queue_deleted = len([book for book in queue if Pipeline.get_main_event(book) == "deleted"]) if queue else 0
            queue_modified = len([book for book in queue if Pipeline.get_main_event(book) == "modified"]) if queue else 0
            queue_triggered = len([book for book in queue if Pipeline.get_main_event(book) == "triggered"]) if queue else 0
            queue_autotriggered = len([book for book in queue if Pipeline.get_main_event(book) == "autotriggered"]) if queue else 0
            if self.debug_logging:
                logging.info("after many invocations of Pipeline.get_main_event(book)")
            queue_string = []
            if queue_created:
                queue_string.append("nye:"+str(queue_created))
            if queue_modified:
                queue_string.append("endret:"+str(queue_modified))
            if queue_deleted:
                queue_string.append("slettet:"+str(queue_deleted))
            if queue_triggered:
                queue_string.append("trigget:"+str(queue_triggered))
            if queue_autotriggered:
                queue_string.append("autotrigget:"+str(queue_autotriggered))
            queue_string = ", ".join(queue_string)

            queue_size = len(queue) if queue else 0
            if self.debug_logging:
                logging.info("before pipeline[0].pipeline_book_shortname()")
            book = Metadata.pipeline_book_shortname(pipeline[0])
            if self.debug_logging:
                logging.info("after pipeline[0].pipeline_book_shortname()")

            relpath_in = None
            netpath_in = ""
            rank_in = None
            if pipeline[0].dir_in:
                for rank in Pipeline.dirs_ranked:
                    for dir in rank["dirs"]:
                        if os.path.normpath(pipeline[0].dir_in) == os.path.normpath(rank["dirs"][dir]):
                            rank_in = rank["id"]
                            break
            if pipeline[0].dir_in and not pipeline[0].dir_base:
                relpath_in = os.path.basename(os.path.dirname(pipeline[0].dir_in))
            elif pipeline[0].dir_in and pipeline[0].dir_base:
                if self.debug_logging:
                    logging.info("before Filesystem.get_base_path(…, …)")
                base_path = Filesystem.get_base_path(pipeline[0].dir_in, pipeline[0].dir_base)
                if self.debug_logging:
                    logging.info("after Filesystem.get_base_path(…, …)")
                relpath_in = os.path.relpath(pipeline[0].dir_in, base_path)
                if "master" in pipeline[0].dir_base and pipeline[0].dir_base["master"] == base_path:
                    pass
                else:
                    if pipeline[0].dir_in not in self.buffered_network_paths:
                        if self.debug_logging:
                            logging.info("before Filesystem.networkpath(…)")
                        smb, file, unc = Filesystem.networkpath(pipeline[0].dir_in)
                        if self.debug_logging:
                            logging.info("after Filesystem.networkpath(…)")
                        if self.debug_logging:
                            logging.info("before Filesystem.get_host_from_url(…)")
                        host = Filesystem.get_host_from_url(smb)
                        if self.debug_logging:
                            logging.info("after Filesystem.get_host_from_url(…)")
                        self.buffered_network_paths[pipeline[0].dir_in] = smb
                        self.buffered_network_hosts[pipeline[0].dir_in] = host
                    netpath_in = self.buffered_network_hosts[pipeline[0].dir_in]
                    if not netpath_in:
                        netpath_in = self.buffered_network_paths[pipeline[0].dir_in]
            if self.debug_logging:
                logging.info("before get_book_count(…)")
            book_count_in = self.get_book_count(pipeline[0].dir_in)
            if self.debug_logging:
                logging.info("after get_book_count(…)")
            label_in = "< <font point-size='24'>{}</font>{}{} >".format(
                relpath_in,
                "\n<br/><i><font point-size='20'>{} {}</font></i>".format(book_count_in, "bok" if book_count_in == 1 else "bøker"),
                "\n<br/><i><font point-size='20'>{}</font></i>".format(netpath_in.replace("\\", "\\\\")) if netpath_in else "")

            relpath_out = None
            netpath_out = ""
            rank_out = None
            if pipeline[0].dir_out:
                for rank in Pipeline.dirs_ranked:
                    for dir in rank["dirs"]:
                        if os.path.normpath(pipeline[0].dir_out) == os.path.normpath(rank["dirs"][dir]):
                            rank_out = rank["id"]
                            break
            if pipeline[0].dir_out and not pipeline[0].dir_base:
                relpath_out = os.path.basename(os.path.dirname(pipeline[0].dir_out))
            elif pipeline[0].dir_out and pipeline[0].dir_base:
                if self.debug_logging:
                    logging.info("before Filesystem.get_base_path(…, …)")
                base_path = Filesystem.get_base_path(pipeline[0].dir_out, pipeline[0].dir_base)
                if self.debug_logging:
                    logging.info("after Filesystem.get_base_path(…, …)")
                relpath_out = os.path.relpath(pipeline[0].dir_out, base_path)
                if "master" in pipeline[0].dir_base and pipeline[0].dir_base["master"] == base_path:
                    pass
                else:
                    if pipeline[0].dir_out not in self.buffered_network_paths:
                        if self.debug_logging:
                            logging.info("before Filesystem.networkpath(…)")
                        smb, file, unc = Filesystem.networkpath(pipeline[0].dir_out)
                        if self.debug_logging:
                            logging.info("after Filesystem.networkpath(…)")
                        if self.debug_logging:
                            logging.info("after Filesystem.get_host_from_url(…)")
                        host = Filesystem.get_host_from_url(smb)
                        if self.debug_logging:
                            logging.info("after Filesystem.get_host_from_url(…)")
                        self.buffered_network_paths[pipeline[0].dir_out] = unc
                        self.buffered_network_hosts[pipeline[0].dir_out] = host
                    netpath_out = self.buffered_network_hosts[pipeline[0].dir_out]
                    if not netpath_out:
                        netpath_out = self.buffered_network_paths[pipeline[0].dir_out]
            if self.debug_logging:
                logging.info("before get_book_count(…)")
            book_count_out = self.get_book_count(pipeline[0].dir_out, pipeline[0].parentdirs)
            if self.debug_logging:
                logging.info("after get_book_count(…)")
            label_out = "< <font point-size='24'>{}</font>{}{} >".format(
                relpath_out,
                "\n<br/><i><font point-size='20'>{} {}</font></i>".format(book_count_out, "bok" if book_count_out == 1 else "bøker"),
                "\n<br/><i><font point-size='20'>{}</font></i>".format(netpath_out.replace("\\", "\\\\")) if netpath_out else "")

            if rank_out:
                node_ranks[rank_out].append(pipeline_id)
            elif rank_in:
                next_rank = self.next_rank(rank_in)
                if next_rank:
                    node_ranks[next_rank].append(pipeline_id)
                else:
                    node_ranks[rank_in].append(pipeline_id)

            if self.debug_logging:
                logging.info("before pipeline[0].get_status()")
            status = pipeline[0].get_status()
            if self.debug_logging:
                logging.info("after pipeline[0].get_status(…)")
            if self.debug_logging:
                logging.info("before pipeline[0].get_progress(…)")
            progress_text = pipeline[0].get_progress()
            if self.debug_logging:
                logging.info("after pipeline[0].get_progress(…)")
            pipeline_label = "< <font point-size='26'>{}</font>{} >".format(
                title,
                "".join(["\n<br/><i><font point-size='22'>{}</font></i>".format(val) for val in [queue_string, progress_text, status] if val]))

            fillcolor = "lightskyblue1"
            if book or queue_size:
                fillcolor = "lightslateblue"
            if not pipeline[0].running or isinstance(pipeline[0], DummyPipeline):
                fillcolor = "white"
            dot.attr("node", shape="box", style="filled", fillcolor=fillcolor)
            dot.node(pipeline_id, pipeline_label.replace("\\", "\\\\"))

            if relpath_in:
                fillcolor = "wheat"
                if self.debug_logging:
                    logging.info("before Pipeline.directory_watchers_ready(…)")
                if not Pipeline.directory_watchers_ready(pipeline[0].dir_in):
                    fillcolor = "white"
                if self.debug_logging:
                    logging.info("after Pipeline.directory_watchers_ready(…)")
                dot.attr("node", shape="folder", style="filled", fillcolor=fillcolor)
                dot.node(pipeline[1], label_in)
                if pipeline[1] not in edges:
                    edges[pipeline[1]] = []
                if pipeline_id not in edges[pipeline[1]]:
                    edges[pipeline[1]].append(pipeline_id)
                    dot.edge(pipeline[1], pipeline_id)
                node_ranks[rank_in].append(pipeline[1])

            if relpath_out:
                fillcolor = "wheat"
                if self.debug_logging:
                    logging.info("before Pipeline.directory_watchers_ready(…)")
                if not Pipeline.directory_watchers_ready(pipeline[0].dir_out):
                    fillcolor = "white"
                if self.debug_logging:
                    logging.info("after Pipeline.directory_watchers_ready(…)")
                dot.attr("node", shape="folder", style="filled", fillcolor=fillcolor)
                dot.node(pipeline[2], label_out)
                if pipeline_id not in edges:
                    edges[pipeline_id] = []
                if pipeline[2] not in edges[pipeline_id]:
                    edges[pipeline_id].append(pipeline[2])
                    dot.edge(pipeline_id, pipeline[2])
                node_ranks[rank_out].append(pipeline[2])

        if self.debug_logging:
            logging.info("before building Digraph")
        for rank in node_ranks:
            subgraph = Digraph("cluster_" + rank, graph_attr={"style": "dotted"})

            if node_ranks[rank]:
                subgraph.attr("node", shape="none", style="filled", fillcolor="white")
                subgraph.node("_ranklabel_" + rank, "< <i><font point-size='28'>{}</font></i> >".format(" <br/>".join(str(self.rank_name(rank)).split(" "))))

            for dir in node_ranks[rank]:
                subgraph.node(dir)

            dot.subgraph(subgraph)
        if self.debug_logging:
            logging.info("after building Digraph")

        if self.debug_logging:
            logging.info("before dot.render(…)")
        dot.render(os.path.join(self.report_dir, name + "_"))
        if self.debug_logging:
            logging.info("after dot.render(…)")

        # there seems to be some race condition when doing this across a mounted network drive,
        # so if we get an exception we retry a few times and hope that it works.
        # see: https://github.com/nlbdev/produksjonssystem/issues/81
        if self.debug_logging:
            logging.info("before race condition workaround")
        for t in reversed(range(10)):
            try:
                if self.debug_logging:
                    logging.info("race condition iteration: {}".format(t))
                shutil.copyfile(os.path.join(self.report_dir, name + "_.png"), os.path.join(self.report_dir, name + ".png"))
                break
            except Exception as e:
                logging.debug(" Unable to copy plot image: {}".format(os.path.join(self.report_dir, name + "_.png")))
                time.sleep(0.5)
                if t == 0:
                    raise e
        if self.debug_logging:
            logging.info("after race condition workaround")

        dashboard_file = os.path.join(self.report_dir, name + ".html")
        if not os.path.isfile(dashboard_file):
            if self.debug_logging:
                logging.info("before creating dashboard file")
            dashboard_template = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), '../../dashboard.html'))
            if not os.path.exists(self.report_dir):
                os.makedirs(self.report_dir)
            shutil.copyfile(dashboard_template, dashboard_file)
            if self.debug_logging:
                logging.info("after creating dashboard file")

    def run(self):
        self.threads = []

        plotter_thread = threading.Thread(target=self._generate_plots_thread, name="graph plotter")
        plotter_thread.setDaemon(True)
        plotter_thread.start()
        self.threads.append(plotter_thread)

        book_count_thread = threading.Thread(target=self._update_book_count_thread, name="graph book count updater")
        book_count_thread.setDaemon(True)
        book_count_thread.start()
        self.threads.append(book_count_thread)

        while self.should_run:
            time.sleep(1)

        self.join()

    def join(self):
        for thread in self.threads:
            if thread:
                logging.debug("joining {}".format(thread.name))
                thread.join(timeout=60)

        is_alive = True
        while is_alive:
            is_alive = False
            for thread in self.threads:
                if thread and thread != threading.current_thread() and thread.is_alive():
                    is_alive = True
                    logging.info("Thread is still running: {}".format(thread.name))
                    thread.join(timeout=60)

    def _generate_plots_thread(self):
        try:
            for name in os.listdir(self.report_dir):
                path = os.path.join(self.report_dir, name)
                if os.path.isfile(path) and path.endswith(".html"):
                    try:
                        os.remove(path)
                    except Exception:
                        logging.exception("An error occurred while deleting existing HTML file")
        except Exception:
            logging.exception("An error occurred while deleting existing HTML files")

        while self.should_run:
            time.sleep(1)
            try:
                self.debug_logging = False
                times = []

                # Main dashboard
                time_start = time.time()
                self.plot([p[0].uid for p in self.pipelines], "dashboard")
                times.append("dashboard: {}s".format(round(time.time() - time_start, 1)))
                if not self.should_run:
                    break

                # Dashboard for steps
#                time_start = time.time()
#                for p in self.pipelines:
#                    self.plot([p[0].uid], p[0].uid)
#                    if not self.should_run:
#                        break
#                times.append("pipelines: {}s".format(round(time.time() - time_start, 1)))
#                if not self.should_run:
#                    break

                # Dashboard for persons
#                time_start = time.time()
#                emails = {}
#                for p in self.pipelines:
#                    for e in p[0].email_settings["recipients"]:
#                        if e not in emails:
#                            emails[e] = []
#                        emails[e].append(p[0].uid)
#                for e in emails:
#                    self.plot(emails[e], e.lower())
#                    if not self.should_run:
#                        break
#                times.append("persons: {}s".format(round(time.time() - time_start, 1)))
#                if not self.should_run:
#                    break

                # Dashboard for labels
                time_start = time.time()
                labels = {}
                for p in self.pipelines:
                    for l in p[0].labels:
                        if l not in labels:
                            labels[l] = []
                        labels[l].append(p[0].uid)
                for l in labels:
                    self.plot(labels[l], l)
                    if not self.should_run:
                        break
                times.append("labels: {}s".format(round(time.time() - time_start, 1)))
                if not self.should_run:
                    break

                if int(time.time()) % 300 == 0:
                    # print only when mod time is 0 so that this is not logged all the time
                    logging.info(", ".join(times))

            except Exception:
                logging.exception("An error occurred while generating plot")

    def _update_book_count_thread(self):
        while self.should_run:
            time.sleep(1)
            try:
                for dir in self.book_count:
                    dirs = []
                    parentdirs = self.book_count[dir]["parentdirs"]
                    if parentdirs:
                        for parentdir in parentdirs:
                            dirs.append(os.path.join(dir, parentdirs[parentdir]))
                    else:
                        dirs.append(dir)
                    if (self.book_count[dir]["modified"] + 15 < time.time()):
                        books = []
                        for d in dirs:
                            if os.path.isdir(d):
                                books += [name for name in os.listdir(d) if name[0] in "0123456789" or name.startswith("TEST")]
                        self.book_count[dir]["modified"] = time.time()
                        self.book_count[dir]["count"] = len(set(books))

                    if not self.should_run:
                        break

            except Exception:
                logging.exception("An error occurred while updating book count")
