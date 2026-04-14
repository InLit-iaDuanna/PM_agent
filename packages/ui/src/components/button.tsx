import {
  Children,
  cloneElement,
  forwardRef,
  isValidElement,
  type ButtonHTMLAttributes,
  type MutableRefObject,
  type PropsWithChildren,
  type ReactElement,
  type Ref,
} from "react";
import { cn } from "../lib/cn";

type ButtonVariant = "primary" | "secondary" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  asChild?: boolean;
}

function assignRef<T>(ref: Ref<T> | undefined, value: T | null) {
  if (!ref) {
    return;
  }
  if (typeof ref === "function") {
    ref(value);
    return;
  }
  (ref as MutableRefObject<T | null>).current = value;
}

function composeRefs<T>(...refs: Array<Ref<T> | undefined>) {
  return (value: T | null) => {
    refs.forEach((ref) => assignRef(ref, value));
  };
}

export const Button = forwardRef<HTMLButtonElement, PropsWithChildren<ButtonProps>>(function Button(
  {
    children,
    className,
    variant = "primary",
    asChild = false,
    ...props
  },
  forwardedRef,
) {
  const classes = cn(
    "inline-flex items-center justify-center rounded-2xl border px-4 py-2.5 text-sm font-medium transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--accent)] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60",
    variant === "primary" &&
      "border-[color:var(--accent)] bg-[linear-gradient(135deg,_rgba(29,76,116,1),_rgba(23,32,51,0.98))] text-white shadow-[0_12px_30px_rgba(29,76,116,0.22)] hover:-translate-y-0.5 hover:shadow-[0_16px_34px_rgba(29,76,116,0.28)]",
    variant === "secondary" &&
      "border-[color:var(--border-soft)] bg-[rgba(255,252,246,0.82)] text-[color:var(--ink)] hover:-translate-y-0.5 hover:border-[color:var(--border-strong)] hover:bg-white",
    variant === "ghost" &&
      "border-transparent bg-transparent text-[color:var(--muted-strong)] hover:border-[color:var(--border-soft)] hover:bg-[rgba(255,255,255,0.5)] hover:text-[color:var(--ink)]",
    className,
  );

  if (asChild && isValidElement(children)) {
    const child = Children.only(children) as ReactElement<{ className?: string }> & { ref?: Ref<unknown> };
    return cloneElement(child as ReactElement<Record<string, unknown>>, {
      ...child.props,
      ...props,
      className: cn(classes, child.props.className),
      ref: composeRefs(child.ref, forwardedRef as Ref<unknown>),
    } as Record<string, unknown>);
  }

  return (
    <button className={classes} ref={forwardedRef} {...props}>
      {children}
    </button>
  );
});

Button.displayName = "Button";
