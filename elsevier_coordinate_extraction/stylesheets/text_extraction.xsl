<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
  xmlns:ce="http://www.elsevier.com/xml/common/dtd"
  xmlns:ja="http://www.elsevier.com/xml/ja/dtd"
    xmlns:sb="http://www.elsevier.com/xml/common/struct-bib/dtd"
    xmlns:dcterms="http://purl.org/dc/terms/"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:xocs="http://www.elsevier.com/xml/xocs/dtd"
  exclude-result-prefixes="ce sb dcterms dc xocs ja">

  <xsl:output method="xml" version="1.0" encoding="UTF-8" omit-xml-declaration="no"/>
  <xsl:strip-space elements="*"/>

  <xsl:template match="/">
    <extracted-text>
      <doi>
        <xsl:value-of select="normalize-space((//dc:identifier[starts-with(., 'doi:')])[1])"/>
      </doi>
      <pii>
        <xsl:value-of select="normalize-space((//xocs:pii-unformatted)[1])"/>
      </pii>
      <title>
        <xsl:value-of select="normalize-space((//dc:title)[1])"/>
      </title>
      <keywords>
        <xsl:apply-templates select="//dcterms:subject" mode="keywords"/>
      </keywords>
      <abstract>
        <xsl:variable name="abstractNode" select="(//ce:abstract)[1]"/>
        <xsl:choose>
          <xsl:when test="$abstractNode">
            <xsl:apply-templates select="$abstractNode"/>
          </xsl:when>
          <xsl:otherwise>
            <xsl:apply-templates select="(//dc:description)[1]"/>
          </xsl:otherwise>
        </xsl:choose>
      </abstract>
      <body>
        <xsl:variable name="bodyNode" select="(//ja:body)[1]"/>
        <xsl:choose>
          <xsl:when test="$bodyNode">
            <xsl:apply-templates select="$bodyNode"/>
          </xsl:when>
          <xsl:otherwise>
            <xsl:apply-templates select="(//ce:sections)[1]"/>
          </xsl:otherwise>
        </xsl:choose>
      </body>
    </extracted-text>
  </xsl:template>

  <xsl:template match="body">
    <xsl:apply-templates select="ce:sections | ce:section | ce:para | *"/>
  </xsl:template>

  <xsl:template match="ja:body">
    <xsl:apply-templates select="ce:sections | ce:section | ce:para | *"/>
  </xsl:template>

  <xsl:template match="ce:sections">
    <xsl:apply-templates/>
  </xsl:template>

  <xsl:template match="ce:section">
    <xsl:text>&#10;</xsl:text>
    <xsl:apply-templates/>
    <xsl:text>&#10;</xsl:text>
  </xsl:template>

  <xsl:template match="ce:section-title">
    <xsl:call-template name="heading">
      <xsl:with-param name="level" select="count(ancestor::ce:section) + 1"/>
    </xsl:call-template>
    <xsl:text> </xsl:text>
    <xsl:apply-templates/>
    <xsl:text>&#10;&#10;</xsl:text>
  </xsl:template>

  <xsl:template name="heading">
    <xsl:param name="level"/>
    <xsl:if test="$level &gt; 0">
      <xsl:text>#</xsl:text>
      <xsl:call-template name="heading">
        <xsl:with-param name="level" select="$level - 1"/>
      </xsl:call-template>
    </xsl:if>
  </xsl:template>

  <xsl:template match="ce:para">
    <xsl:text>&#10;</xsl:text>
    <xsl:apply-templates/>
    <xsl:text>&#10;</xsl:text>
  </xsl:template>

  <xsl:template match="ce:list">
    <xsl:text>&#10;</xsl:text>
    <xsl:apply-templates/>
    <xsl:text>&#10;</xsl:text>
  </xsl:template>

  <xsl:template match="ce:list-item">
    <xsl:text>- </xsl:text>
    <xsl:apply-templates/>
    <xsl:text>&#10;</xsl:text>
  </xsl:template>

  <xsl:template match="ce:simple-para">
    <xsl:apply-templates/>
  </xsl:template>

  <xsl:template match="text()" mode="keywords"/>

  <xsl:template match="dcterms:subject" mode="keywords">
    <xsl:value-of select="normalize-space(.)"/>
    <xsl:text>&#10;</xsl:text>
  </xsl:template>

  <xsl:template match="text()">
    <xsl:value-of select="normalize-space(.)"/>
    <xsl:text> </xsl:text>
  </xsl:template>

  <xsl:template match="
      ce:acknowledgment |
      ce:bibliography |
      ce:bib-reference |
      ce:table |
      ce:figure |
      ce:caption |
      ce:legend |
      ce:label |
      ce:cross-ref |
      ce:cross-refs |
      ce:footnote |
      ce:floats |
      ce:inline-figure |
      ce:inline-formula |
      ce:display-formula |
      ce:graphic |
      ce:supplementary-material |
      ce:supplement |
      ce:references |
      ce:ref |
      sb:reference |
      sb:contribution |
      sb:host |
      sb:pages |
      sb:authors |
      sb:author
    " />

  <xsl:template match="*">
    <xsl:apply-templates/>
  </xsl:template>

</xsl:stylesheet>
