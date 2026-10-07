<script lang="ts">
  // First-run setup (a new install; Settings > General > Setup runs it again): the interface language, VRChat's OSC,
  // and the avatar's KuraDot version (picked by hand: it must match the prefab on the avatar).
  import Check from "@lucide/svelte/icons/check";
  import * as Dialog from "$lib/components/ui/dialog";
  import * as Select from "$lib/components/ui/select";
  import { Button } from "$lib/components/ui/button";
  import { app } from "$lib/app.svelte";
  import { HTML_LANG, i18n, LANGS, setLang, t, type Lang } from "$lib/i18n.svelte";
  import { cn } from "$lib/utils";

  const STEPS = 4;
  let step = $state(0);
  let osc = $state<"on" | "later" | null>(null);
  let avatar = $state<"full" | "standard" | "lite" | "none" | null>(null);
  let busy = $state(false);

  // a new run starts at the beginning, with the current version preselected
  $effect(() => {
    if (app.setupOpen) {
      step = 0;
      osc = null;
      const tier = app.kd?.settings?.tier;
      avatar = app.out.kd && tier ? tier : null;
    }
  });

  const target = $derived(app.cfg?.osc ? `${app.cfg.osc.host}:${app.cfg.osc.port}` : "127.0.0.1:9000");
  const AVATARS = ["full", "standard", "lite", "none"] as const;
  const canNext = $derived(step === 0 || (step === 1 && osc !== null) || (step === 2 && avatar !== null) || step === 3);

  async function finish() {
    busy = true;
    try {
      await app.finishSetup(avatar === "none" || avatar === null ? null : avatar);
    } finally {
      busy = false;
    }
  }

  const card = (on: boolean) => cn("flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-muted/60",
    on && "border-primary bg-primary/5 ring-primary ring-1");
</script>

<Dialog.Root bind:open={app.setupOpen} onOpenChange={(o) => { if (!o) app.skipSetup(); }}>
  <Dialog.Content class="flex max-h-[92dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-lg" showCloseButton={false}
    interactOutsideBehavior="ignore">
    <Dialog.Header class="border-b px-5 py-4">
      <div class="text-muted-foreground mb-1 flex items-center gap-1.5 text-xs" aria-label={t("setup.step", { n: step + 1, total: STEPS })}>
        {#each Array.from({ length: STEPS }, (_, i) => i) as i (i)}
          <span class={cn("h-1.5 w-8 rounded-full", i <= step ? "bg-primary" : "bg-muted")}></span>
        {/each}
        <span class="ml-2">{t("setup.step", { n: step + 1, total: STEPS })}</span>
      </div>
      <Dialog.Title>{t(`setup.title${step}` as any)}</Dialog.Title>
      <Dialog.Description>{t(`setup.desc${step}` as any)}</Dialog.Description>
    </Dialog.Header>

    <div class="min-h-0 flex-1 overflow-y-auto px-5 py-4 text-sm">
      {#if step === 0}
        <div class="flex items-center justify-between gap-3">
          <span class="font-medium">{t("gen.language")}</span>
          <Select.Root type="single" value={i18n.lang} onValueChange={(v) => setLang(v as Lang)}>
            <Select.Trigger size="sm" class="w-40">{LANGS.find(([k]) => k === i18n.lang)?.[1]}</Select.Trigger>
            <Select.Content>
              {#each LANGS as [k, name] (k)}<Select.Item value={k} lang={HTML_LANG[k]}>{name}</Select.Item>{/each}
            </Select.Content>
          </Select.Root>
        </div>
        <ul class="text-muted-foreground mt-4 list-disc space-y-1 pl-5">
          <li>{t("setup.intro1")}</li>
          <li>{t("setup.intro2")}</li>
        </ul>
      {:else if step === 1}
        <ol class="list-decimal space-y-1.5 pl-5">
          <li>{t("setup.osc1")}</li>
          <li>{t("setup.osc2")}</li>
          <li>{t("setup.osc3")}</li>
        </ol>
        <p class="text-muted-foreground mt-3">{t("setup.oscTarget", { target })}</p>
        <p class="mt-4 mb-2 font-medium">{t("setup.oscAsk")}</p>
        <div class="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label={t("setup.oscAsk")}>
          {#each [["on", "setup.oscOn"], ["later", "setup.oscLater"]] as [v, k] (v)}
            <button type="button" role="radio" aria-checked={osc === v} class={card(osc === v)} onclick={() => (osc = v as any)}>
              <span class={cn("mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border", osc === v && "border-primary bg-primary text-primary-foreground")}>
                {#if osc === v}<Check class="size-3" />{/if}</span>
              <span>{t(k as any)}</span>
            </button>
          {/each}
        </div>
      {:else if step === 2}
        <div class="grid gap-2" role="radiogroup" aria-label={t("setup.title2")}>
          {#each AVATARS as v (v)}
            <button type="button" role="radio" aria-checked={avatar === v} class={card(avatar === v)} onclick={() => (avatar = v)}>
              <span class={cn("mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border", avatar === v && "border-primary bg-primary text-primary-foreground")}>
                {#if avatar === v}<Check class="size-3" />{/if}</span>
              <span class="flex flex-col gap-0.5">
                <span class="font-medium">{t(`setup.av.${v}` as any)}</span>
                <span class="text-muted-foreground text-xs">{t(`setup.av.${v}Desc` as any)}</span>
              </span>
            </button>
          {/each}
        </div>
        <p class="text-muted-foreground mt-3 text-xs">{t("setup.avHint")}</p>
      {:else}
        <ul class="space-y-2">
          <li class="flex gap-2"><Check class={cn("mt-0.5 size-4 shrink-0", osc === "on" ? "text-primary" : "text-muted-foreground")} />
            {osc === "on" ? t("setup.sumOscOn") : t("setup.sumOscLater")}</li>
          <li class="flex gap-2"><Check class="text-primary mt-0.5 size-4 shrink-0" />
            {avatar === "none" ? t("setup.sumNone") : t("setup.sumAvatar", { v: t(`setup.av.${avatar}` as any) })}</li>
        </ul>
        <p class="text-muted-foreground mt-4">{t("setup.sumLater")}</p>
      {/if}
    </div>

    <div class="flex items-center justify-between gap-2 border-t px-5 py-3">
      <Button variant="ghost" size="sm" onclick={() => app.skipSetup()}>{t("setup.skip")}</Button>
      <div class="flex gap-2">
        {#if step > 0}<Button variant="outline" size="sm" onclick={() => step--}>{t("setup.back")}</Button>{/if}
        {#if step < STEPS - 1}
          <Button size="sm" disabled={!canNext} onclick={() => step++}>{t("setup.next")}</Button>
        {:else}
          <Button size="sm" disabled={busy} onclick={finish}>{t("setup.finish")}</Button>
        {/if}
      </div>
    </div>
  </Dialog.Content>
</Dialog.Root>
