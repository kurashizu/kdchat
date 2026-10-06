<script lang="ts">
  // one setting: a label (+ description) on the left, its control on the right (stacked on narrow screens)
  import type { Snippet } from "svelte";
  import { cn } from "$lib/utils";

  let { label, desc = "", id = undefined, disabled = false, stack = false, class: className = "", children }:
    { label: string; desc?: string; id?: string; disabled?: boolean; stack?: boolean; class?: string; children: Snippet } = $props();
</script>

<div class={cn("flex gap-x-6 gap-y-2 py-3", stack ? "flex-col" : "flex-col sm:flex-row sm:items-center sm:justify-between",
  disabled && "opacity-50", className)}>
  <div class="min-w-0 space-y-0.5">
    <label for={id} class="text-sm font-medium leading-none">{label}</label>
    {#if desc}<p class="text-muted-foreground text-xs leading-snug">{desc}</p>{/if}
  </div>
  <div class={cn("shrink-0", stack && "w-full")}>{@render children()}</div>
</div>
