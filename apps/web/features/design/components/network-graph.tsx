"use client";

import { useEffect, useMemo, useRef } from "react";
import * as d3 from "d3";

import type { NetworkData, NetworkLink, NetworkNode } from "../data/trend-types";

type ControlAction = { type: "zoom_in" | "center" | "reset"; token: number } | null;

interface NetworkGraphProps {
  data: NetworkData;
  width: number;
  height: number;
  onNodeClick: (nodeId: string) => void;
  onNodeHover: (nodeId: string | null) => void;
  highlightNodeId?: string;
  threshold?: number;
  categoryFilter?: string;
  showLabels?: boolean;
  clusterColored?: boolean;
  controlAction?: ControlAction;
}

type SimNode = NetworkNode & d3.SimulationNodeDatum;
type SimLink = d3.SimulationLinkDatum<SimNode> & NetworkLink;

const GROUP_COLORS = ["#2563EB", "#0EA5E9", "#D97706", "#7C3AED", "#14B8A6", "#F43F5E", "#0F172A", "#475569"];

export function NetworkGraph({
  data,
  width,
  height,
  onNodeClick,
  onNodeHover,
  highlightNodeId,
  threshold = 0.15,
  categoryFilter = "全部",
  showLabels = true,
  clusterColored = true,
  controlAction,
}: NetworkGraphProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const zoomBehaviorRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const svgSelectionRef = useRef<d3.Selection<SVGSVGElement, unknown, null, undefined> | null>(null);

  const filtered = useMemo(() => {
    const links = data.links.filter(
      (link) => link.weight >= threshold && (categoryFilter === "全部" || !categoryFilter || link.shared_category === categoryFilter),
    );
    const nodeIds = new Set<string>();
    links.forEach((link) => {
      nodeIds.add(link.source);
      nodeIds.add(link.target);
    });
    const nodes = nodeIds.size > 0 ? data.nodes.filter((node) => nodeIds.has(node.id)) : data.nodes;
    return { nodes, links };
  }, [categoryFilter, data.links, data.nodes, threshold]);

  useEffect(() => {
    if (!svgRef.current || width <= 0 || height <= 0) {
      return;
    }

    const svg = d3.select(svgRef.current);
    svgSelectionRef.current = svg;
    svg.selectAll("*").remove();

    const nodes: SimNode[] = filtered.nodes.map((node) => ({ ...node }));
    const links: SimLink[] = filtered.links.map((link) => ({ ...link }));
    const getNodeId = (value: string | SimNode) => (typeof value === "string" ? value : value.id);

    const defs = svg.append("defs");
    const backgroundGradient = defs
      .append("radialGradient")
      .attr("id", "network-bg-gradient")
      .attr("cx", "50%")
      .attr("cy", "50%")
      .attr("r", "75%");
    backgroundGradient.append("stop").attr("offset", "0%").attr("stop-color", "rgba(255,255,255,0.98)");
    backgroundGradient.append("stop").attr("offset", "100%").attr("stop-color", "rgba(226,232,240,0.55)");

    svg
      .append("rect")
      .attr("width", width)
      .attr("height", height)
      .attr("fill", "url(#network-bg-gradient)");

    const root = svg.append("g");

    const zoomBehavior = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .on("zoom", (event) => {
        root.attr("transform", event.transform.toString());
      });
    zoomBehaviorRef.current = zoomBehavior;
    svg.call(zoomBehavior as never);

    const simulation = d3
      .forceSimulation<SimNode>(nodes)
      .force(
        "link",
        d3
          .forceLink<SimNode, SimLink>(links)
          .id((datum) => datum.id)
          .distance((datum) => 120 - datum.weight * 60)
          .strength((datum) => Math.max(0.1, datum.weight * 0.8)),
      )
      .force("charge", d3.forceManyBody().strength(-220))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide<SimNode>().radius((node) => (node.id === highlightNodeId ? 40 : 34)));

    const linkSelection = root
      .append("g")
      .attr("class", "network-links")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("class", "network-link")
      .attr("stroke-width", (link) => Math.max(0.5, link.weight * 3))
      .attr("stroke", (link) => {
        if (!clusterColored) {
          return "rgba(71,85,105,0.55)";
        }
        const sharedCategory = link.shared_category || "default";
        const paletteIndex = Math.abs(sharedCategory.length) % GROUP_COLORS.length;
        return GROUP_COLORS[paletteIndex];
      })
      .attr("stroke-opacity", (link) => Math.max(0.12, link.weight))
      .attr("stroke-dasharray", "2 3");

    linkSelection.append("title").text((link) => `${link.shared_tags.join(" / ") || "颜色或风格相近"} · ${Math.round(link.weight * 100)}%`);

    const nodeSelection = root
      .append("g")
      .attr("class", "network-nodes")
      .selectAll("g")
      .data(nodes)
      .join("g")
      .attr("class", "network-node")
      .style("cursor", "pointer");

    nodeSelection.each(function(node) {
      defs
        .append("clipPath")
        .attr("id", `clip-${node.id}`)
        .append("circle")
        .attr("r", 24);
    });

    nodeSelection
      .append("circle")
      .attr("r", (node) => (node.id === highlightNodeId ? 34 : 28))
      .attr("fill", (node) => `${node.colors[0] || "#CBD5E1"}33`)
      .attr("stroke", (node) => (clusterColored ? GROUP_COLORS[node.group % GROUP_COLORS.length] : "rgba(15,23,42,0.12)"))
      .attr("stroke-width", (node) => (node.id === highlightNodeId ? 3 : 2));

    nodeSelection
      .append("image")
      .attr("href", (node) => node.thumbnail)
      .attr("x", -24)
      .attr("y", -24)
      .attr("width", 48)
      .attr("height", 48)
      .attr("clip-path", (node) => `url(#clip-${node.id})`)
      .attr("preserveAspectRatio", "xMidYMid slice");

    nodeSelection
      .append("circle")
      .attr("r", 24)
      .attr("fill", "transparent")
      .attr("stroke", "rgba(255,255,255,0.95)")
      .attr("stroke-width", 2);

    nodeSelection
      .filter((node) => node.source === "trend")
      .append("circle")
      .attr("r", 31)
      .attr("fill", "transparent")
      .attr("stroke", "#F59E0B")
      .attr("stroke-width", 2)
      .attr("stroke-dasharray", "4 3");

    const labelSelection = nodeSelection
      .append("text")
      .attr("y", 44)
      .attr("text-anchor", "middle")
      .attr("font-size", 11)
      .attr("font-weight", 600)
      .attr("fill", "var(--ink)")
      .text((node) => node.label)
      .style("opacity", showLabels ? 0.92 : 0);

    nodeSelection.append("title").text((node) => `${node.label}\n${node.tags.slice(0, 6).join(" / ")}`);

    const connectedById = new Set(links.flatMap((link) => {
      const sourceId = getNodeId(link.source);
      const targetId = getNodeId(link.target);
      return [`${sourceId}::${targetId}`, `${targetId}::${sourceId}`];
    }));
    const isConnected = (leftId: string, rightId: string) => leftId === rightId || connectedById.has(`${leftId}::${rightId}`);

    const applyFocusState = (focusId: string | null) => {
      linkSelection.attr("stroke-opacity", (link) => {
        if (!focusId) {
          return Math.max(0.12, link.weight);
        }
        return getNodeId(link.source) === focusId || getNodeId(link.target) === focusId ? 1 : 0.08;
      });
      nodeSelection.attr("opacity", (node) => {
        if (!focusId) {
          return 1;
        }
        return isConnected(focusId, node.id) ? 1 : 0.28;
      });
      nodeSelection.selectAll<SVGCircleElement, SimNode>("circle:first-child").attr("r", (node) => {
        if (node.id === highlightNodeId) {
          return focusId && isConnected(focusId, node.id) ? 38 : 34;
        }
        return focusId && isConnected(focusId, node.id) ? 32 : 28;
      });
      labelSelection.style("opacity", (node) => {
        if (showLabels) {
          return !focusId || isConnected(focusId, node.id) ? 0.92 : 0.18;
        }
        return focusId && isConnected(focusId, node.id) ? 0.88 : 0;
      });
    };

    nodeSelection
      .on("mouseenter", (_, node) => {
        onNodeHover(node.id);
        applyFocusState(node.id);
      })
      .on("mouseleave", () => {
        onNodeHover(null);
        applyFocusState(highlightNodeId ?? null);
      })
      .on("click", (_, node) => {
        onNodeClick(node.id);
      });

    nodeSelection.call(
      d3
        .drag<SVGGElement, SimNode>()
        .on("start", (event, node) => {
          if (!event.active) {
            simulation.alphaTarget(0.3).restart();
          }
          node.fx = node.x;
          node.fy = node.y;
        })
        .on("drag", (event, node) => {
          node.fx = event.x;
          node.fy = event.y;
        })
        .on("end", (event, node) => {
          if (!event.active) {
            simulation.alphaTarget(0);
          }
          node.fx = null;
          node.fy = null;
        }) as never,
    );

    simulation.on("tick", () => {
      linkSelection
        .attr("x1", (link) => (link.source as SimNode).x ?? 0)
        .attr("y1", (link) => (link.source as SimNode).y ?? 0)
        .attr("x2", (link) => (link.target as SimNode).x ?? 0)
        .attr("y2", (link) => (link.target as SimNode).y ?? 0);

      nodeSelection.attr("transform", (node) => `translate(${node.x ?? 0},${node.y ?? 0})`);
    });

    applyFocusState(highlightNodeId ?? null);

    return () => {
      simulation.stop();
      svg.selectAll("*").remove();
    };
  }, [
    clusterColored,
    filtered.links,
    filtered.nodes,
    height,
    highlightNodeId,
    onNodeClick,
    onNodeHover,
    showLabels,
    width,
  ]);

  useEffect(() => {
    const svg = svgSelectionRef.current;
    const zoomBehavior = zoomBehaviorRef.current;
    if (!svg || !zoomBehavior || !controlAction) {
      return;
    }
    if (controlAction.type === "zoom_in") {
      svg.transition().duration(240).call(zoomBehavior.scaleBy as never, 1.25);
      return;
    }
    if (controlAction.type === "center") {
      svg.transition().duration(320).call(
        zoomBehavior.transform as never,
        d3.zoomIdentity.translate(width / 2, height / 2).scale(1).translate(-width / 2, -height / 2),
      );
      return;
    }
    svg.transition().duration(320).call(zoomBehavior.transform as never, d3.zoomIdentity);
  }, [controlAction, height, width]);

  if (width <= 0 || height <= 0) {
    return null;
  }

  return (
    <div className="absolute inset-0 overflow-hidden">
      <svg ref={svgRef} width={width} height={height} className="block">
        <style>{`
          .network-link {
            animation: networkPulse 2s ease-in-out infinite;
          }
          @keyframes networkPulse {
            0%, 100% { stroke-opacity: 0.45; }
            50% { stroke-opacity: 0.72; }
          }
        `}</style>
      </svg>
    </div>
  );
}
