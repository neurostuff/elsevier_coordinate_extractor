<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:ce="http://www.elsevier.com/xml/common/dtd"
    xmlns:cals="http://www.elsevier.com/xml/common/cals/dtd"
    xmlns:tb="http://www.elsevier.com/xml/common/table/dtd"
    exclude-result-prefixes="ce cals tb">

  <xsl:output method="xml" indent="no" encoding="UTF-8"/>
  <xsl:strip-space elements="*"/>

  <xsl:template match="/">
    <extracted-tables-set>
      <xsl:apply-templates select=".//ce:table"/>
    </extracted-tables-set>
  </xsl:template>

  <xsl:template match="ce:table">
    <xsl:variable name="tableId" select="@id"/>
    <extracted-table>
      <table-id>
        <xsl:value-of select="@id"/>
      </table-id>
      <table-label>
        <xsl:value-of select="normalize-space(ce:label)"/>
      </table-label>
      <table-caption>
        <xsl:value-of select="normalize-space(ce:caption)"/>
      </table-caption>
      <table-legend>
        <xsl:value-of select="normalize-space(ce:legend)"/>
      </table-legend>
      <table-wrap-foot>
        <xsl:value-of select="normalize-space(ce:table-foot)"/>
      </table-wrap-foot>
      <reference-sentences>
        <xsl:if test="$tableId">
          <xsl:variable name="refParas" select="
            (//ce:cross-ref[contains(concat(' ', normalize-space(@refid), ' '), concat(' ', $tableId, ' '))] |
             //ce:cross-refs[contains(concat(' ', normalize-space(@refid), ' '), concat(' ', $tableId, ' '))])
            /ancestor::*[self::ce:para or self::ce:simple-para][1]
          "/>
          <xsl:for-each select="$refParas">
            <sentence>
              <xsl:value-of select="normalize-space(.)"/>
            </sentence>
          </xsl:for-each>
        </xsl:if>
      </reference-sentences>
      <original-table>
        <xsl:copy-of select="."/>
      </original-table>
      <transformed-table>
        <table>
          <xsl:apply-templates select="cals:tgroup | ce:tgroup | tb:tgroup" mode="html"/>
        </table>
      </transformed-table>
    </extracted-table>
  </xsl:template>

  <xsl:template match="cals:tgroup | ce:tgroup | tb:tgroup" mode="html">
    <xsl:apply-templates select="cals:thead | ce:thead | tb:thead" mode="html"/>
    <xsl:apply-templates select="cals:tbody | ce:tbody | tb:tbody" mode="html"/>
    <xsl:apply-templates select="cals:tfoot | ce:tfoot | tb:tfoot" mode="html"/>
  </xsl:template>

  <xsl:template match="cals:thead | ce:thead | tb:thead" mode="html">
    <thead>
      <xsl:apply-templates select="cals:row | ce:row | tb:row" mode="html"/>
    </thead>
  </xsl:template>

  <xsl:template match="cals:tbody | ce:tbody | tb:tbody" mode="html">
    <tbody>
      <xsl:apply-templates select="cals:row | ce:row | tb:row" mode="html"/>
    </tbody>
  </xsl:template>

  <xsl:template match="cals:tfoot | ce:tfoot | tb:tfoot" mode="html">
    <tfoot>
      <xsl:apply-templates select="cals:row | ce:row | tb:row" mode="html"/>
    </tfoot>
  </xsl:template>

  <xsl:template match="cals:row | ce:row | tb:row" mode="html">
    <tr>
      <xsl:apply-templates select="cals:entry | ce:entry | tb:entry" mode="html"/>
    </tr>
  </xsl:template>

  <xsl:template match="cals:entry | ce:entry | tb:entry" mode="html">
    <xsl:variable name="namest" select="@namest"/>
    <xsl:variable name="nameend" select="@nameend"/>
    <xsl:variable name="morerows" select="@morerows"/>
    <xsl:choose>
      <xsl:when test="ancestor::cals:thead">
        <th>
          <xsl:call-template name="apply-span-attributes">
            <xsl:with-param name="namest" select="$namest"/>
            <xsl:with-param name="nameend" select="$nameend"/>
            <xsl:with-param name="morerows" select="$morerows"/>
          </xsl:call-template>
          <xsl:apply-templates/>
        </th>
      </xsl:when>
      <xsl:otherwise>
        <td>
          <xsl:call-template name="apply-span-attributes">
            <xsl:with-param name="namest" select="$namest"/>
            <xsl:with-param name="nameend" select="$nameend"/>
            <xsl:with-param name="morerows" select="$morerows"/>
          </xsl:call-template>
          <xsl:apply-templates/>
        </td>
      </xsl:otherwise>
    </xsl:choose>
  </xsl:template>

  <xsl:template name="apply-span-attributes">
    <xsl:param name="namest"/>
    <xsl:param name="nameend"/>
    <xsl:param name="morerows"/>
    <xsl:if test="$namest and $nameend">
      <xsl:variable name="start" select="number(substring($namest, 4))"/>
      <xsl:variable name="end" select="number(substring($nameend, 4))"/>
      <xsl:if test="not(number($start) != $start or number($end) != $end)">
        <xsl:attribute name="colspan">
          <xsl:value-of select="$end - $start + 1"/>
        </xsl:attribute>
      </xsl:if>
    </xsl:if>
    <xsl:if test="$morerows">
      <xsl:attribute name="rowspan">
        <xsl:value-of select="number($morerows) + 1"/>
      </xsl:attribute>
    </xsl:if>
  </xsl:template>

</xsl:stylesheet>
