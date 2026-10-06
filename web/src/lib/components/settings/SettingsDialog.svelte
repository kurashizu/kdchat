<script lang="ts">
  import Info from "@lucide/svelte/icons/info";
  import Languages from "@lucide/svelte/icons/languages";
  import MonitorSmartphone from "@lucide/svelte/icons/monitor-smartphone";
  import Network from "@lucide/svelte/icons/network";
  import SlidersHorizontal from "@lucide/svelte/icons/sliders-horizontal";
  import * as Dialog from "$lib/components/ui/dialog";
  import * as Tabs from "$lib/components/ui/tabs";
  import AboutTab from "./AboutTab.svelte";
  import ConnectionTab from "./ConnectionTab.svelte";
  import DisplayTab from "./DisplayTab.svelte";
  import GeneralTab from "./GeneralTab.svelte";
  import TranslationTab from "./TranslationTab.svelte";
  import { app } from "$lib/app.svelte";
  import { t } from "$lib/i18n.svelte";

  // a column of tabs on the left on wide screens, a scrolling row on top on phones
  const mq = window.matchMedia("(min-width: 768px)");
  let wide = $state(mq.matches);
  mq.addEventListener("change", () => (wide = mq.matches));

  let body = $state<HTMLDivElement>();
  $effect(() => { app.settingsTab; if (body) body.scrollTop = 0; });   // a new tab starts at its top

  const TABS = [
    { v: "general", icon: SlidersHorizontal, label: () => t("tab.general") },
    { v: "display", icon: MonitorSmartphone, label: () => t("tab.display") },
    { v: "translation", icon: Languages, label: () => t("tab.translation") },
    { v: "connection", icon: Network, label: () => t("tab.connection") },
    { v: "about", icon: Info, label: () => t("tab.about") },
  ];
</script>

<Dialog.Root bind:open={app.settingsOpen}>
  <Dialog.Content class="flex h-[min(46rem,92dvh)] flex-col gap-0 overflow-hidden p-0 sm:max-w-3xl">
    <Dialog.Header class="border-b px-5 py-4">
      <Dialog.Title>{t("settings.title")}</Dialog.Title>
      <Dialog.Description>{t("settings.desc")}</Dialog.Description>
    </Dialog.Header>
    <Tabs.Root bind:value={app.settingsTab} orientation={wide ? "vertical" : "horizontal"} class="flex min-h-0 flex-1 flex-col gap-0 md:flex-row">
      <Tabs.List variant="line" class={wide ? "h-auto w-48 shrink-0 items-stretch justify-start gap-1 rounded-none border-r p-2"
        : "!h-auto w-full shrink-0 justify-start gap-1 overflow-x-auto rounded-none border-b px-2 py-1.5"}>
        {#each TABS as tab (tab.v)}
          <Tabs.Trigger value={tab.v} class="data-[state=active]:bg-muted flex-none justify-start gap-2 px-3 py-2 data-[state=active]:shadow-none">
            <tab.icon class="size-4" />{tab.label()}
          </Tabs.Trigger>
        {/each}
      </Tabs.List>
      <div bind:this={body} class="min-h-0 flex-1 overflow-y-auto px-5 py-3">
        <Tabs.Content value="general"><GeneralTab /></Tabs.Content>
        <Tabs.Content value="display"><DisplayTab /></Tabs.Content>
        <Tabs.Content value="translation"><TranslationTab /></Tabs.Content>
        <Tabs.Content value="connection"><ConnectionTab /></Tabs.Content>
        <Tabs.Content value="about"><AboutTab /></Tabs.Content>
      </div>
    </Tabs.Root>
  </Dialog.Content>
</Dialog.Root>
