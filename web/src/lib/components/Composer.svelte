<script lang="ts">
  import CornerDownLeft from "@lucide/svelte/icons/corner-down-left";
  import ImageIcon from "@lucide/svelte/icons/image";
  import Keyboard from "@lucide/svelte/icons/keyboard";
  import MessageSquareText from "@lucide/svelte/icons/message-square-text";
  import MonitorSmartphone from "@lucide/svelte/icons/monitor-smartphone";
  import Pencil from "@lucide/svelte/icons/pencil";
  import Radio from "@lucide/svelte/icons/radio";
  import SendHorizontal from "@lucide/svelte/icons/send-horizontal";
  import X from "@lucide/svelte/icons/x";
  import { onMount } from "svelte";
  import { Button } from "$lib/components/ui/button";
  import { Toggle } from "$lib/components/ui/toggle";
  import * as ToggleGroup from "$lib/components/ui/toggle-group";
  import * as Tooltip from "$lib/components/ui/tooltip";
  import TranslateQuick from "./TranslateQuick.svelte";
  import { app, type Target } from "$lib/app.svelte";
  import { t } from "$lib/i18n.svelte";
  import { cn } from "$lib/utils";
  import { toast } from "svelte-sonner";

  let ta = $state<HTMLTextAreaElement>(null!);
  let { phone = false }: { phone?: boolean } = $props();

  const edit = $derived(app.cur?.mode === "edit");
  const anyOut = $derived(app.out.chatbox || app.out.kd);
  const lines = $derived(app.text ? app.text.split("\n").length : 0);
  const near = $derived(app.text.length > app.limits.chars * 0.8 || lines > app.limits.lines - 2);
  const status = $derived(app.busy ? "sending" : app.cur && app.live && app.cur.id != null && app.cur.mode === "new" ? "live"
    : app.typingOn ? "typing" : null);
  const toNames = $derived(app.curTargets.map((k) => t(k === "kd" ? "out.kdShort" : "out.chatboxShort")).join(" + "));
  const pictureNote = $derived(app.out.kd && app.kdStat?.image && app.curTargets.includes("kd"));

  function resize() {
    if (!ta) return;
    ta.style.height = "auto";
    const cap = phone ? 140 : 260;
    ta.style.height = Math.min(cap, Math.max(phone ? 40 : 76, ta.scrollHeight + 2)) + "px";
  }
  $effect(() => {
    app.text;
    queueMicrotask(resize);
  });

  function onKey(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.isComposing && e.keyCode !== 229) {
      const send = app.enterSends ? !e.shiftKey : e.ctrlKey || e.metaKey;
      if (send) {
        e.preventDefault();
        app.commit();
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      app.cancel(false);
    }
  }

  function pickTargets(v: string[]) {
    if (!v.length) return; // never none
    app.setSendTo(v as Target[]);
    // a message not on the server yet (nothing shown live) still goes where it is sent now; one already shown keeps
    // its outputs (the change applies to the next one)
    if (app.cur && app.cur.mode === "new") {
      if (app.cur.id == null) {
        app.cur.targets = app.targetsNow();
        app.syncSoon(0);
      }
      else toast(t("composer.sendToLocked"));
    }
  }

  // the send button / toggles must not take the focus from the text (phones: the keyboard stays open)
  const keep = (e: PointerEvent) => { if (document.activeElement === ta) e.preventDefault(); };

  onMount(() => {
    if (!phone) ta?.focus();
    app.focusComposer = () => { ta?.focus(); ta?.setSelectionRange(app.text.length, app.text.length); };
    return () => { app.focusComposer = null; };
  });
</script>

<section class={cn("bg-card text-card-foreground rounded-xl border shadow-xs transition-colors",
  edit && "border-primary/60 ring-primary/20 ring-3", app.over && "border-destructive/60")} aria-label={t("composer.ph")}>
  {#if edit}
    <div class="bg-primary/10 flex items-center gap-2 rounded-t-xl border-b px-3 py-2 text-sm">
      <Pencil class="text-primary size-4 shrink-0" />
      <span class="font-medium">{t("composer.editing")}</span>
      <span class="text-muted-foreground min-w-0 flex-1 truncate">{app.cur?.original}</span>
      <Button size="xs" variant="ghost" onclick={() => app.cancel(false)}>{t("composer.cancel")}</Button>
    </div>
  {/if}

  <textarea bind:this={ta} bind:value={app.text} oninput={() => app.onInput()} onkeydown={onKey}
    rows="1" enterkeyhint={app.enterSends ? "send" : "enter"} autocomplete="off" disabled={!anyOut}
    placeholder={anyOut ? t("composer.ph") : t("out.noneOn")}
    class="placeholder:text-muted-foreground block w-full resize-none bg-transparent px-3.5 pt-3 pb-1 text-base leading-relaxed outline-none disabled:cursor-not-allowed sm:text-[15px]"></textarea>

  {#if pictureNote}
    <p class="flex items-center gap-1.5 px-3.5 pb-1 text-xs text-amber-600 dark:text-amber-400">
      <ImageIcon class="size-3.5" />{t("composer.picture")}</p>
  {/if}

  <div class="flex flex-wrap items-center gap-1.5 px-2 pt-1 pb-2">
    <Tooltip.Root>
      <Tooltip.Trigger>
        {#snippet child({ props })}
          <div {...props} class="inline-flex">
            <ToggleGroup.Root type="multiple" variant="outline" size="sm" value={app.curTargets}
              onValueChange={pickTargets} aria-label={t("composer.sendTo")}>
              <ToggleGroup.Item value="chatbox" disabled={!app.out.chatbox} onpointerdown={keep}
                aria-label={t("out.chatbox")}>
                <MessageSquareText /><span class="max-sm:sr-only">{t("out.chatboxShort")}</span>
              </ToggleGroup.Item>
              <ToggleGroup.Item value="kd" disabled={!app.out.kd} onpointerdown={keep}
                aria-label={t("out.kd")}>
                <MonitorSmartphone /><span class="max-sm:sr-only">{t("out.kdShort")}</span>
              </ToggleGroup.Item>
            </ToggleGroup.Root>
          </div>
        {/snippet}
      </Tooltip.Trigger>
      <Tooltip.Content class="max-w-64">
        <p class="font-medium">{t("composer.sendTo")}: {toNames}</p>
        <p class="opacity-80">{app.cur?.mode === "new" && app.cur.id != null ? t("composer.sendToLocked") : app.both ? t("composer.sendToTip") : ""}</p>
      </Tooltip.Content>
    </Tooltip.Root>

    <TranslateQuick />

    <Tooltip.Root>
      <Tooltip.Trigger>
        {#snippet child({ props })}
          <Toggle {...props} variant="outline" size="sm" pressed={app.live} onPressedChange={(v) => app.setPref("live", v)}
            onpointerdown={keep} aria-label={t("composer.liveTip")}
            class="">
            <Radio class={cn(status === "live" && "animate-pulse")} />
            <span class="max-sm:sr-only">{t("composer.live")}</span>
          </Toggle>
        {/snippet}
      </Tooltip.Trigger>
      <Tooltip.Content class="max-w-64">{t("gen.liveDesc")}</Tooltip.Content>
    </Tooltip.Root>

    {#if app.out.chatbox && !edit}
      <Tooltip.Root>
        <Tooltip.Trigger>
          {#snippet child({ props })}
            <Button {...props} variant="ghost" size="sm" onpointerdown={keep} onclick={() => app.fillKeyboard()}
              disabled={!app.text.trim()} aria-label={t("composer.kbFillTip")}>
              <Keyboard /><span class="max-md:sr-only">{t("composer.kbFill")}</span>
            </Button>
          {/snippet}
        </Tooltip.Trigger>
        <Tooltip.Content>{t("composer.kbFillTip")}</Tooltip.Content>
      </Tooltip.Root>
    {/if}

    <div class="ml-auto flex items-center gap-2">
      {#if status}
        <span class={cn("text-xs max-sm:hidden", status === "live" ? "text-primary" : "text-muted-foreground")} aria-live="polite">
          {t(`composer.status.${status}`)}</span>
      {/if}
      <span class={cn("text-muted-foreground text-xs tabular-nums", app.over ? "text-destructive font-medium" : phone && !near && "hidden")}
        title={app.over ? t("composer.tooLong", { where: toNames }) : ""}>
        {app.text.length}/{app.limits.chars}{lines > 1 ? ` · ${t("composer.lines", { l: lines, maxl: app.limits.lines })}` : ""}
      </span>
      {#if app.cur && !edit}
        <Button variant="ghost" size="sm" onclick={() => app.cancel(false)} title={t("composer.cancelTip")}>
          <X /><span class="max-sm:sr-only">{t("composer.cancel")}</span>
        </Button>
      {/if}
      <Button size="sm" onpointerdown={keep} onclick={() => app.commit()} disabled={!app.text.trim() || app.over || !anyOut}
        title={edit ? t("composer.save") : `${t("composer.sendTo")}: ${toNames}`} class="min-w-20">
        {#if edit}<CornerDownLeft />{t("composer.save")}{:else}<SendHorizontal />{t("composer.send")}{/if}
      </Button>
    </div>
  </div>
  {#if !phone}
    <p class="text-muted-foreground/70 border-t px-3.5 py-1.5 text-[11px]">{app.enterSends ? t("composer.keys") : t("composer.keysNl")}</p>
  {/if}
</section>
