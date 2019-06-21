#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import threading
from pathlib import Path
from random import random

import requests
from flask import Flask, Response, jsonify, redirect, request

from core.pipeline import DummyPipeline, Pipeline
from core.utils.filesystem import Filesystem
from core.utils.metadata import Metadata


class API():
    """
    API for communicating with the production system.
    """
    version = 1

    app = None
    base_url = None
    host = None
    port = None
    root_path = None

    kill_endpoint = "/kill{}/".format(str(random()).split(".")[-1])  # random endpoint to discourage explicit external usage

    buffered_network_paths = {}
    buffered_network_hosts = {}

    def __init__(self, root_path="/prodsys", include_version=True):
        self.app = Flask(__name__)
        self.host = os.getenv("API_HOST", default="0.0.0.0")
        self.port = os.getenv("API_PORT", default=3875)
        self.root_path = "{}{}".format(root_path, "/v{}".format(API.version) if include_version else "")
        self.base_url = "http://{}{}{}".format(self.host,
                                               ":{}".format(self.port) if self.port != 80 else "",
                                               self.root_path)

        # declaring endpoints here, as instance decorators doesn't seem to work

        # root endpoint
        self.app.add_url_rule(self.root_path+"/", "root", self.root)

        # forward endpoints "above" the root, to the root (i.e. /prodsys/ and /prodsys/v1/)
        if self.root_path != "":
            self.app.add_url_rule("/", "root", self.root)
            parts = [part for part in self.root_path.split("/") if part]
            endpoints_above = ["/".join(parts[0:i+1]) for i in range(0, len(parts)-1)]
            for endpoint in endpoints_above:
                self.app.add_url_rule("/{}/".format(endpoint), "root", self.root)

        # the easiest way to shut down Flask is through an instance of request,
        # so we create this endpoint which gives us a request instance
        self.app.add_url_rule(self.root_path + API.kill_endpoint, "kill", self.kill, methods=["POST"])

        self.app.add_url_rule(self.root_path+"/creative-works/",
                              "creative-works",
                              self.creativeWorks)

        self.app.add_url_rule(self.root_path+"/pipelines/",
                              "pipelines",
                              self.pipelines)

        self.app.add_url_rule(self.root_path+"/pipelines/<pipeline_id>/",
                              "pipeline",
                              self.pipeline)

        self.app.add_url_rule(self.root_path+"/pipelines/<pipeline_id>/creative-works/",
                              "pipeline_creativeWorks",
                              self.pipeline_creativeWorks)

        self.app.add_url_rule(self.root_path+"/pipelines/<pipeline_id>/editions/",
                              "pipeline_editions",
                              self.pipeline_editions)

        self.app.add_url_rule(self.root_path+"/pipelines/<pipeline_id>/editions/<edition_id>/",
                              "pipeline_edition",
                              self.pipeline_edition)

        self.app.add_url_rule(self.root_path+"/pipelines/<pipeline_id>/editions/<edition_id>/trigger/",
                              "pipeline_trigger",
                              self.pipeline_trigger,
                              methods=["GET", "POST"])

        self.app.add_url_rule(self.root_path+"/directories/",
                              "directories",
                              self.directories)

        self.app.add_url_rule(self.root_path+"/directories/<directory_id>/",
                              "directory",
                              self.directory)

        self.app.add_url_rule(self.root_path+"/directories/<directory_id>/editions/",
                              "directory_editions",
                              self.directory_editions)

        self.app.add_url_rule(self.root_path+"/directories/<directory_id>/editions/<edition_id>/",
                              "directory_edition",
                              self.directory_edition)

        self.app.add_url_rule(self.root_path+"/directories/<directory_id>/editions/<edition_id>/trigger/",
                              "directory_trigger",
                              self.directory_trigger,
                              methods=["GET", "POST"])

    def start(self, hot_reload=False):
        """
        Start thread
        """

        # app.run should ideally not be used in production, but oh well…
        self.thread = threading.Thread(target=self.app.run, name="api", kwargs={
            "debug": hot_reload,
            "host": self.host,
            "port": self.port
        })
        self.thread.setDaemon(True)
        self.thread.start()

    def join(self):
        """
        Stop thread
        """

        requests.post(self.base_url + API.kill_endpoint)

        logging.debug("joining {}".format(self.thread.name))
        self.thread.join(timeout=60)

        if self.thread.isAlive():
            logging.debug("The API thread is still running. Let's ignore it and continue shutdown…")

    # endpoint: /creative-works
    def creativeWorks(self):
        # [ "<isbn>", "<isbn>", "<isbn>", "-<edition_id>", "-<edition_id>", "-<edition_id>" ]
        return "TODO"

    # endpoint: /pipelines
    def pipelines(self):
        result = {}
        for pipeline in Pipeline.pipelines:
            result[pipeline.uid] = pipeline.title
        return jsonify(result)

    # endpoint: /pipelines/<pipeline_id>
    def pipeline(self, pipeline_id):
        pipeline = [pipeline for pipeline in Pipeline.pipelines if pipeline.uid == pipeline_id]
        pipeline = pipeline[0] if pipeline else None

        if not pipeline:
            return Response(None, status=404)

        dir_in_id = None
        dir_out_id = None
        for dir in Pipeline.dirs_flat:
            if os.path.isdir(pipeline.dir_in) and os.path.normpath(pipeline.dir_in) == os.path.normpath(Pipeline.dirs_flat[dir]):
                dir_in_id = dir
            if os.path.isdir(pipeline.dir_out) and os.path.normpath(pipeline.dir_out) == os.path.normpath(Pipeline.dirs_flat[dir]):
                dir_out_id = dir

        return jsonify({
            "uid": pipeline.uid,
            "title": pipeline.title,
            "dir_in": dir_in_id,
            "dir_out": dir_out_id,
            "parentdirs": pipeline.parentdirs,
            "labels": pipeline.labels,
            "publication_format": pipeline.publication_format,
            "expected_processing_time": pipeline.expected_processing_time,
            "state": pipeline.get_state(),
            "queue": pipeline.get_queue()
        })

    # endpoint: /pipelines/<pipeline_id>/creative-works
    def pipeline_creativeWorks(self, pipeline_id):
        # { "<edition_id>": }
        return "TODO"

    # endpoint: /pipelines/<pipeline_id>/editions
    def pipeline_editions(self, pipeline_id):
        pipeline = [pipeline for pipeline in Pipeline.pipelines if pipeline.uid == pipeline_id]
        pipeline = pipeline[0] if pipeline else None

        if not pipeline:
            return Response(None, status=404)

        else:
            directory_id = [dir for dir in Pipeline.dirs_flat if os.path.normpath(Pipeline.dirs_flat[dir]) == os.path.normpath(pipeline.dir_out)][:1]
            directory_id = directory_id[0] if directory_id else None
            return self.directory_editions(directory_id)

    # endpoint: /pipelines/<pipeline_id>/editions/<edition_id>
    def pipeline_edition(self, pipeline_id, edition_id):
        pipeline = [pipeline for pipeline in Pipeline.pipelines if pipeline.uid == pipeline_id]
        pipeline = pipeline[0] if pipeline else None

        if not pipeline:
            return Response(None, status=404)

        else:
            directory_id = [dir for dir in Pipeline.dirs_flat if os.path.normpath(Pipeline.dirs_flat[dir]) == os.path.normpath(pipeline.dir_out)][:1]
            directory_id = directory_id[0] if directory_id else None
            return self.directory_edition(directory_id, edition_id)

    # endpoint: /pipelines/<pipeline_id>/editions/<edition_id>/trigger
    def pipeline_trigger(self, pipeline_id, edition_id):
        pipeline = [pipeline for pipeline in Pipeline.pipelines if pipeline.uid == pipeline_id]
        pipeline = pipeline[0] if pipeline else None

        if not pipeline:
            return Response(None, status=404)

        else:
            pipeline.trigger(edition_id, auto=False)
            return jsonify([pipeline_id])

    # endpoint: /directories
    def directories(self):
        structure = request.args.get('structure', 'simple')

        if structure == "ranked":
            return jsonify(Pipeline.dirs_ranked)

        elif structure == "resolved":
            dirs = {}

            for dir in Pipeline.dirs_flat:
                if dir not in self.buffered_network_paths:
                    smb, file, unc = Filesystem.networkpath(Pipeline.dirs_flat[dir])
                    host = Filesystem.get_host_from_url(smb)
                    self.buffered_network_paths[dir] = smb
                    self.buffered_network_hosts[dir] = host
                dirs[dir] = self.buffered_network_paths[dir]

            return jsonify(dirs)

        else:
            return jsonify(Pipeline.dirs_flat)

    # endpoint: /directories/<directory_id>
    def directory(self, directory_id):
        path = os.path.normpath(Pipeline.dirs_flat.get(directory_id, None))
        if path:
            result = {
                "path": Pipeline.dirs_flat.get(directory_id, None),
                "input_pipelines": [],
                "output_pipelines": []
            }
            for pipeline in Pipeline.pipelines:
                if os.path.normpath(pipeline.dir_out) == path:
                    result["input_pipelines"].append(pipeline.uid)
                if os.path.normpath(pipeline.dir_in) == path:
                    result["output_pipelines"].append(pipeline.uid)
            return jsonify(result)
        else:
            return Response(None, status=404)

    # endpoint: /directories/<directory_id>/editions
    def directory_editions(self, directory_id):
        path = Pipeline.dirs_flat.get(directory_id, None)
        if not path:
            return Response(None, status=404)

        elif not os.path.isdir(path):
            return Response(None, status=404)

        else:
            return jsonify([Path(file).stem for file in os.listdir(path)])

    # endpoint: /directories/<directory_id>/editions/<edition_id>
    def directory_edition(self, directory_id, edition_id):
        path = os.path.normpath(Pipeline.dirs_flat.get(directory_id, None))

        if not path:
            return Response(None, status=404)

        book_path = None
        for name in os.listdir(path):
            if Path(name).stem == edition_id:
                book_path = os.path.join(path, name)
                break

        if not book_path:
            return Response(None, status=404)

        force_update = request.args.get('force_update', "false").lower() == "true"
        extend_with_cached_rdf_metadata = request.args.get('extend_with_cached_rdf_metadata', "true").lower() == "true"

        return jsonify(Metadata.get_metadata_from_book(DummyPipeline(),
                                                       book_path,
                                                       force_update=force_update,
                                                       extend_with_cached_rdf_metadata=extend_with_cached_rdf_metadata))

    # endpoint: /directories/<directory_id>/editions/<edition_id>/trigger
    def directory_trigger(self, directory_id, edition_id):
        path = os.path.normpath(Pipeline.dirs_flat.get(directory_id, None))

        if not path:
            return Response(None, status=404)

        file_stems = [Path(file).stem for file in os.listdir(path)]
        if edition_id not in file_stems:
            return Response(None, status=404)

        result = []
        for pipeline in Pipeline.pipelines:
            if os.path.normpath(pipeline.dir_in) == path:
                pipeline.trigger(edition_id, auto=False)
                result.append(pipeline.uid)
        return jsonify(result)

    # endpoint: /
    def root(self):
        """
        Root endpoint. Lists all possible endpoints.
        """
        endpoint = request.url[len(request.url_root)-1:]
        if endpoint != self.root_path+"/":
            return redirect(self.root_path+"/", code=302)
        else:
            rules = []
            for rule in self.app.url_map.iter_rules():
                rules.append(str(rule))
            return jsonify(rules)

    # endpoint: /kill
    def kill(self):
        """
        Used internally for shutting down. Should not be used by exernal applications.
        """
        # See:
        # - http://flask.pocoo.org/snippets/67/
        # - https://stackoverflow.com/a/26788325/281065

        shutdown = request.environ.get("werkzeug.server.shutdown")
        if shutdown is None:
            raise RuntimeError("Not running with the Werkzeug Server")
        shutdown()
        return "Shutting down…"