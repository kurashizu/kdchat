<script lang="ts">
  import MessageSquareText from "@lucide/svelte/icons/message-square-text";
  import MonitorSmartphone from "@lucide/svelte/icons/monitor-smartphone";
  import Settings from "@lucide/svelte/icons/settings";
  import { Button } from "$lib/components/ui/button";
  import { Switch } from "$lib/components/ui/switch";
  import * as Tooltip from "$lib/components/ui/tooltip";
  import { app, type Target } from "$lib/app.svelte";
  import { ask } from "$lib/confirm.svelte";
  import { t } from "$lib/i18n.svelte";
  import { cn } from "$lib/utils";

  const outputs: { k: Target; icon: typeof MessageSquareText; name: () => string; short: () => string; desc: () => string }[] = [
    { k: "chatbox", icon: MessageSquareText, name: () => t("out.chatbox"), short: () => t("out.chatboxShort"), desc: () => t("out.chatboxDesc") },
    { k: "kd", icon: MonitorSmartphone, name: () => t("out.kd"), short: () => t("out.kdShort"), desc: () => t("out.kdDesc") },
  ];

  async function toggle(k: Target) {
    const on = !app.out[k];
    if (!on && k === "kd" && !(await ask({ title: t("out.confirmKdOffTitle"), desc: t("out.confirmKdOff"), action: t("out.turnOff"), remember: "kdOff" }))) return;
    app.setOutput(k, on);
  }

  const connText = $derived(t(app.conn === "ok" ? "conn.online" : app.conn === "warn" ? "conn.noHost" : app.conn === "bad" ? "conn.offline" : "conn.connecting"));
  const target = $derived(app.cfg ? `${app.cfg.osc.host}:${app.cfg.osc.port}` : "…");
</script>

<header class="bg-background/85 sticky top-0 z-30 border-b backdrop-blur supports-[backdrop-filter]:bg-background/70">
  <div class="mx-auto flex h-14 max-w-6xl items-center gap-2 px-3 sm:gap-3 sm:px-4">
    <a href="/" class="flex shrink-0 items-center gap-2 font-semibold tracking-tight">
      <img src="/icon.svg" alt="" class="size-6" />
      <span class="max-sm:hidden">{t("app.name")}</span>
    </a>

    <Tooltip.Root>
      <Tooltip.Trigger class="text-muted-foreground flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs">
        <span class={cn("size-2 rounded-full", app.conn === "ok" ? "bg-emerald-500" : app.conn === "warn" ? "bg-amber-500" : app.conn === "bad" ? "bg-red-500" : "bg-muted-foreground animate-pulse")}></span>
        <span class="max-md:sr-only">{connText}</span>
      </Tooltip.Trigger>
      <Tooltip.Content>{t("conn.tip", { state: connText, target })}</Tooltip.Content>
    </Tooltip.Root>

    <div class="ml-auto flex items-center gap-1 sm:gap-2" role="group" aria-label={t("out.label")}>
      {#each outputs as o (o.k)}
        {@const disabled = o.k === "kd" && !app.kdAvailable}
        <Tooltip.Root>
          <Tooltip.Trigger>
            {#snippet child({ props })}
              <button {...props} type="button" {disabled} onclick={() => toggle(o.k)} aria-pressed={app.out[o.k]}
                class={cn("flex h-9 items-center gap-2 rounded-lg border px-2.5 text-sm transition-colors disabled:opacity-50",
                  app.out[o.k] ? "border-primary/40 bg-primary/10 text-foreground" : "text-muted-foreground hover:bg-muted")}>
                <o.icon class="size-4" />
                <span class="max-sm:hidden">{o.short()}</span>
                <Switch size="sm" checked={app.out[o.k]} tabindex={-1} aria-hidden="true" class="pointer-events-none" />
              </button>
            {/snippet}
          </Tooltip.Trigger>
          <Tooltip.Content class="max-w-64">
            <p class="font-medium">{o.name()}</p>
            <p class="opacity-80">{disabled ? t("out.unavailable") : o.desc()}</p>
          </Tooltip.Content>
        </Tooltip.Root>
      {/each}
      <Button variant="ghost" size="icon" aria-label={t("settings.open")} onclick={() => app.openSettings()}>
        <Settings />
      </Button>
    </div>
  </div>
</header>
