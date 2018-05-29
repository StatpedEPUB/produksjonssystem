<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:fnk="http://www.nlb.no/2017/functions/"
    xmlns:nlb="http://www.nlb.no/2018/xml" xmlns:epub="http://www.idpf.org/2007/ops"
    xpath-default-namespace="http://www.w3.org/1999/xhtml" xmlns="http://www.w3.org/1999/xhtml"
    exclude-result-prefixes="#all" version="2.0">

    <!-- 
        (c) 2018 NLB
        
        Denne transformasjonen brukes på XHTML-dokumentet i en NLBPUB-fil for å gjøre dette dokumenetet optimalt for 
        innlesing av fulltekstlydbøker.
        
        Denne trasnformasjonen fjerner enkelte elementer som ikke skal være med i lydbokutgaven.
        
        Denne transformasjonen etterfølges av en hovedtransformasjonen prepare-for-narration.xsl.
        
        Følgende elementer fjernes:
        * Kolofonen, det vil si section med epub:type som inneholder 'colophon'
        
        Per Sennels, 29.05.2018
    -->

    <xsl:output method="xhtml" indent="yes" include-content-type="no"/>

    <xsl:function name="fnk:epub-type" as="xs:boolean">
        <xsl:param name="attributtverdi" as="xs:string?"/>
        <xsl:param name="type" as="xs:string"/>

        <xsl:value-of
            select="
                some $a in tokenize(normalize-space($attributtverdi), '\s')
                    satisfies $a eq $type"
        />
    </xsl:function>

    <xsl:template match="/">
        <xsl:message>ta-vekk-innhold.xsl (1.0.0 / 2018-05-29)</xsl:message>
        <xsl:next-match/>
    </xsl:template>


    <xsl:template match="@* | node()" priority="-5" mode="#all">
        <xsl:copy exclude-result-prefixes="#all">
            <xsl:apply-templates select="@* | node()"/>
        </xsl:copy>
    </xsl:template>

    
    <!-- **************************** FJERNER KOLOFON *********************************************** -->
    
    <!-- Følgende template fjerner kolofonen -->
    <xsl:template match="section[fnk:epub-type(@epub:type, 'colophon')]">
        <xsl:message>* Fjerner kolofonen</xsl:message>
        <xsl:comment>Kolofonen er fjernet i lydbokutgaven</xsl:comment>
    </xsl:template>
    
    <!-- og dersom det kommer et section-elementet etter kolofonen, så hentes pagebreak fra det fjernede elementet til begynnelsen av dette elementet -->
    <xsl:template
        match="section[fnk:epub-type(preceding-sibling::section[1]/@epub:type, 'colophon')]">
        <xsl:copy exclude-result-prefixes="#all">
            <xsl:copy-of select="@*"/>
            
            <xsl:message>* Henter sidetall fra kolofonen som er fjernet</xsl:message>
            <xsl:copy-of
                select="preceding-sibling::section[1]/descendant::element()[fnk:epub-type(@epub:type, 'pagebreak')]"/>
            
            <xsl:apply-templates/>
        </xsl:copy>
    </xsl:template>
    

</xsl:stylesheet>
