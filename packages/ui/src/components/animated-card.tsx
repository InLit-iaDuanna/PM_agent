import { type HTMLAttributes, type PropsWithChildren, useRef, useEffect, useState } from "react";
import { cn } from "../lib/cn";

interface AnimatedCardProps extends HTMLAttributes<HTMLDivElement> {
  /** 入场动画延迟（ms），配合列表 stagger 使用 */
  delay?: number;
  /** 是否启用 hover 微升效果，默认 true */
  lift?: boolean;
  /** 是否使用 IntersectionObserver 触发入场（滚动触发），默认 false */
  scrollReveal?: boolean;
}

/**
 * AnimatedCard — 带微交互的卡片
 *
 * 在原有 Card 基础上增加：
 * 1. stagger 入场动画（fade-up）
 * 2. hover 微升（translateY -2px + 阴影加深）
 * 3. 可选的 scroll-reveal
 *
 * 用法：
 *   <AnimatedCard delay={120}>内容</AnimatedCard>
 *   <AnimatedCard lift={false} scrollReveal>内容</AnimatedCard>
 */
export function AnimatedCard({
  children,
  className,
  delay = 0,
  lift = true,
  scrollReveal = false,
  style,
  ...props
}: PropsWithChildren<AnimatedCardProps>) {
  const ref = useRef<HTMLDivElement>(null);
  const [revealed, setRevealed] = useState(!scrollReveal);

  useEffect(() => {
    if (!scrollReveal || !ref.current) return;
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) { setRevealed(true); observer.disconnect(); } },
      { threshold: 0.1 },
    );
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [scrollReveal]);

  return (
    <div
      ref={ref}
      className={cn(
        "glass-panel rounded-[30px] p-5 shadow-[0_20px_45px_rgba(23,32,51,0.08)] sm:p-6",
        lift && "transition-[transform,box-shadow] duration-200 ease-[cubic-bezier(0.4,0,0.2,1)] hover:-translate-y-0.5 hover:shadow-[0_24px_52px_rgba(23,32,51,0.12)]",
        scrollReveal && !revealed && "opacity-0 translate-y-2",
        scrollReveal && revealed  && "opacity-100 translate-y-0 transition-[opacity,transform] duration-[350ms] ease-[cubic-bezier(0,0,0.2,1)]",
        !scrollReveal && "animate-fade-up",
        className,
      )}
      style={{
        animationDelay: !scrollReveal ? `${delay}ms` : undefined,
        animationFillMode: "both",
        transitionDelay: scrollReveal && revealed ? `${delay}ms` : undefined,
        ...style,
      }}
      {...props}
    >
      {children}
    </div>
  );
}

/**
 * AnimatedList — 自动 stagger 列表容器
 *
 * 对每个子项自动附加递增的 delay：
 *   <AnimatedList staggerMs={50}>
 *     {items.map(item => <AnimatedCard key={item.id}>...</AnimatedCard>)}
 *   </AnimatedList>
 *
 * 注：需要子组件是 AnimatedCard 或接受 style.animationDelay 的元素。
 */
export function AnimatedList({
  children,
  staggerMs = 50,
  className,
}: PropsWithChildren<{ staggerMs?: number; className?: string }>) {
  // 直接通过 CSS custom property 注入 delay
  return (
    <div className={className}>
      {Array.isArray(children)
        ? children.map((child, i) =>
            child
              ? <div key={i} className="stagger-item" style={{ "--delay": `${i * staggerMs}ms` } as React.CSSProperties}>{child}</div>
              : null,
          )
        : children}
    </div>
  );
}
