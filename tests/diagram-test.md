---
title: "Pandoc 中文图形测试"
author: "pandoc-cn"
date: "2026-06-01"
---

# 中文内容

这份文档用于验证 Docker 镜像中的 Pandoc 能够处理中文、表格，以及 draw.io、PlantUML、Mermaid 三类文本图形，并输出 DOCX 与 PDF。

## 表格

| 模块 | 输入格式 | 期望结果 |
| --- | --- | --- |
| draw.io | `.drawio` XML 代码块 | 渲染为 PNG 图片 |
| PlantUML | `plantuml` 代码块 | 渲染为 PNG 图片 |
| Mermaid | `mermaid` 代码块 | 渲染为 PNG 图片 |

## draw.io 图形

```{.drawio}
<mxfile host="app.diagrams.net" modified="2026-06-01T00:00:00.000Z" agent="pandoc-cn-test" version="30.0.4" type="device">
  <diagram id="pandoc-cn-drawio" name="Page-1">
    <mxGraphModel dx="1066" dy="645" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="850" pageHeight="1100" math="0" shadow="0">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="start" value="开始" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=16;" vertex="1" parent="1">
          <mxGeometry x="80" y="120" width="120" height="50" as="geometry"/>
        </mxCell>
        <mxCell id="process" value="处理中文文档" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=16;" vertex="1" parent="1">
          <mxGeometry x="270" y="120" width="160" height="50" as="geometry"/>
        </mxCell>
        <mxCell id="end" value="输出 DOCX / PDF" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=16;" vertex="1" parent="1">
          <mxGeometry x="500" y="120" width="160" height="50" as="geometry"/>
        </mxCell>
        <mxCell id="edge1" value="" style="endArrow=block;html=1;rounded=0;strokeWidth=2;" edge="1" parent="1" source="start" target="process">
          <mxGeometry width="50" height="50" relative="1" as="geometry">
            <mxPoint x="240" y="145" as="sourcePoint"/>
            <mxPoint x="270" y="145" as="targetPoint"/>
          </mxGeometry>
        </mxCell>
        <mxCell id="edge2" value="" style="endArrow=block;html=1;rounded=0;strokeWidth=2;" edge="1" parent="1" source="process" target="end">
          <mxGeometry width="50" height="50" relative="1" as="geometry">
            <mxPoint x="430" y="145" as="sourcePoint"/>
            <mxPoint x="500" y="145" as="targetPoint"/>
          </mxGeometry>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

## PlantUML 图形

```{.plantuml}
@startuml
title PlantUML 中文时序图
actor 用户
participant "Pandoc 容器" as C
participant "图形工具链" as T

用户 -> C: 提交 Markdown
C -> T: 渲染图形代码块
T --> C: 返回 PNG 图片
C --> 用户: 生成 DOCX 和 PDF
@enduml
```

## Mermaid 图形

```{.mermaid}
flowchart LR
  A[开始] --> B{包含图形?}
  B -- 是 --> C[调用 Mermaid CLI]
  B -- 否 --> D[直接转换文本]
  C --> E[嵌入 PNG]
  D --> E
  E --> F[生成文档]
```
