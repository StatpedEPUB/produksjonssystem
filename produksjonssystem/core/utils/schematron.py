# -*- coding: utf-8 -*-

import os
import re
import lxml
import time
import logging
import tempfile
import subprocess

from lxml import etree as ElementTree
from core.utils.xslt import Xslt

class Schematron():
    """Class used to validate XML documents using Schematron"""
    
    uid = "core-utils-schematron"
    schematron_dir = os.path.join(Xslt.xslt_dir, uid, "schematron/trunk/schematron/code")
    
    # treat as instance variables
    pipeline = None
    
    def __init__(self, pipeline=None, schematron=None, source=None, report=None):
        assert pipeline
        assert schematron and "/" in schematron and os.path.isfile(schematron)
        assert source and "/" in source and os.path.isfile(source)
        
        self.pipeline = pipeline
        self.success = False
        
        try:
            temp_xml_1_obj = tempfile.NamedTemporaryFile()
            temp_xml_1 = temp_xml_1_obj.name
            
            temp_xml_2_obj = tempfile.NamedTemporaryFile()
            temp_xml_2 = temp_xml_2_obj.name
            
            temp_xml_3_obj = tempfile.NamedTemporaryFile()
            temp_xml_3 = temp_xml_3_obj.name
            
            temp_xml_report_obj = tempfile.NamedTemporaryFile()
            temp_xml_report = temp_xml_report_obj.name
            
            self.pipeline.utils.report.debug("Compiling schematron ({} + {}): iso_dsdl_include.xsl".format(os.path.basename(schematron), os.path.basename(source)))
            xslt = Xslt(pipeline, stylesheet=os.path.join(self.schematron_dir, "iso_dsdl_include.xsl"),    source=schematron, target=temp_xml_1,      stdout_level="DEBUG", stderr_level="DEBUG")
            if not xslt.success:
                return
            
            self.pipeline.utils.report.debug("Compiling schematron ({} + {}): iso_abstract_expand.xsl".format(os.path.basename(schematron), os.path.basename(source)))
            xslt = Xslt(pipeline, stylesheet=os.path.join(self.schematron_dir, "iso_abstract_expand.xsl"), source=temp_xml_1, target=temp_xml_2,      stdout_level="DEBUG", stderr_level="DEBUG")
            if not xslt.success:
                return
            
            self.pipeline.utils.report.debug("Compiling schematron ({} + {}): iso_svrl_for_xslt2.xsl".format(os.path.basename(schematron), os.path.basename(source)))
            xslt = Xslt(pipeline, stylesheet=os.path.join(self.schematron_dir, "iso_svrl_for_xslt2.xsl"),  source=temp_xml_2, target=temp_xml_3,      stdout_level="DEBUG", stderr_level="DEBUG")
            if not xslt.success:
                return
            
            self.pipeline.utils.report.debug("Validating against compiled Schematron ({} + {}): iso_svrl_for_xslt2.xsl".format(os.path.basename(schematron), os.path.basename(source)))
            xslt = Xslt(pipeline, stylesheet=temp_xml_3,                                                   source=source,     target=temp_xml_report, stdout_level="DEBUG", stderr_level="DEBUG")
            if not xslt.success:
                return
            
            # Count number of errors
            svrl_schematron_output = ElementTree.parse(temp_xml_report).getroot()
            errors = svrl_schematron_output.findall('{http://purl.oclc.org/dsdl/svrl}failed-assert')
            errors.extend(svrl_schematron_output.findall('{http://purl.oclc.org/dsdl/svrl}successful-report'))
            if len(errors) == 0:
                self.success = True
            else:
                max_errors = 20
                e = 0
                pattern_title = None
                for element in svrl_schematron_output.getchildren():
                    if element.tag == '{http://purl.oclc.org/dsdl/svrl}active-pattern':
                        pattern_title = element.attrib["name"] if "name" in element.attrib else None
                        continue
                    
                    if element.tag == '{http://purl.oclc.org/dsdl/svrl}failed-assert' or element.tag == '{http://purl.oclc.org/dsdl/svrl}successful-report':
                        
                        location = element.attrib["location"] if "location" in element.attrib else None
                        test = element.attrib["test"] if "test" in element.attrib else None
                        text = element.find('{http://purl.oclc.org/dsdl/svrl}text')
                        text = text.text if text is not None and text.text else "(missing description)"
                        
                        if e < max_errors:
                            self.pipeline.utils.report.error((pattern_title + ": " if pattern_title else "") + text)
                        self.pipeline.utils.report.debug((pattern_title + ": " if pattern_title else "") + text + (" ({})".format(location) if location else "") + (" ({})".format(test) if test else ""))
                        
                        e += 1
            
            # Create HTML report
            if report and "/" in report:
                self.pipeline.utils.report.debug("Creating HTML report for Schematron validation ({} + {}): iso_svrl_for_xslt2.xsl".format(os.path.basename(schematron), os.path.basename(source)))
                xslt = Xslt(pipeline, stylesheet=os.path.join(Xslt.xslt_dir, Schematron.uid, "svrl-to-html.xsl"), source=temp_xml_report, target=report)
                if not xslt.success:
                    return
            
        except Exception:
            logging.exception("An error occured while running the Schematron (" + str(schematron) + ")")
            self.pipeline.utils.report.error("An error occured while running the Schematron (" + str(schematron) + ")")
    
    # in case you want to override something
    @staticmethod
    def translate(english_text, translated_text):
        Filesystem._i18n[english_text] = translated_text
    