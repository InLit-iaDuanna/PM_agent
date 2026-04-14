"use client";

import { useEffect, useState } from "react";

/**
 * ReadProgressBar — 报告阅读进度细线
 *
 * 固定在视口顶部，宽度随页面滚动比例变化。
 * 在 ResearchReportPage 顶部 mount 即可自动工作。
 *
 * 用法：
 *   // 在报告页最外层 div 内，顶部放置
 *   <ReadProgressBar />
 */
export function ReadProgressBar() {
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const update = () => {
      const scrollTop  = window.scrollY;
      const docHeight  = document.documentElement.scrollHeight - window.innerHeight;
      setProgress(docHeight > 0 ? Math.min(100, (scrollTop / docHeight) * 100) : 0);
    };

    window.addEventListener("scroll", update, { passive: true });
    update();
    return () => window.removeEventListener("scroll", update);
  }, []);

  return (
    <div
      aria-hidden
      className="read-progress"
      style={{ width: `${progress}%` }}
    />
  );
}
