<script setup lang="ts">
import { ChevronLeft, ChevronRight, X } from "@lucide/vue";
import { onMounted, onUnmounted, ref } from "vue";

const props = defineProps<{ srcs: string[]; index: number }>();
const emit = defineEmits<{ close: [] }>();

const current = ref(props.index);

function close() {
  emit("close");
}
function prev() {
  current.value = (current.value - 1 + props.srcs.length) % props.srcs.length;
}
function next() {
  current.value = (current.value + 1) % props.srcs.length;
}
function onKey(event: KeyboardEvent) {
  if (event.key === "Escape") close();
  if (event.key === "ArrowLeft" && props.srcs.length > 1) prev();
  if (event.key === "ArrowRight" && props.srcs.length > 1) next();
}

onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <div class="lightbox" role="dialog" aria-label="图片预览" @click="close">
    <button
      class="lightbox-close"
      type="button"
      aria-label="关闭预览"
      @click.stop="close"
    >
      <X />
    </button>
    <button
      v-if="srcs.length > 1"
      class="lightbox-nav lightbox-prev"
      type="button"
      aria-label="上一张"
      @click.stop="prev"
    >
      <ChevronLeft />
    </button>
    <img :src="srcs[current]" alt="图片预览" @click.stop />
    <button
      v-if="srcs.length > 1"
      class="lightbox-nav lightbox-next"
      type="button"
      aria-label="下一张"
      @click.stop="next"
    >
      <ChevronRight />
    </button>
    <div v-if="srcs.length > 1" class="lightbox-count">
      {{ current + 1 }} / {{ srcs.length }}
    </div>
  </div>
</template>

<style scoped>
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgb(3 7 19 / 86%);
}
.lightbox img {
  max-width: 92vw;
  max-height: 90vh;
  border-radius: 10px;
  box-shadow: var(--shadow-raised);
}
.lightbox-close {
  position: absolute;
  top: 20px;
  right: 24px;
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border: none;
  border-radius: 50%;
  color: #fff;
  background: rgb(255 255 255 / 14%);
  cursor: pointer;
}
.lightbox-close svg {
  width: 20px;
  height: 20px;
}
.lightbox-nav {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 46px;
  height: 46px;
  display: grid;
  place-items: center;
  border: none;
  border-radius: 50%;
  color: #fff;
  background: rgb(255 255 255 / 14%);
  cursor: pointer;
}
.lightbox-nav svg {
  width: 22px;
  height: 22px;
}
.lightbox-prev {
  left: 24px;
}
.lightbox-next {
  right: 24px;
}
.lightbox-count {
  position: absolute;
  bottom: 22px;
  left: 50%;
  transform: translateX(-50%);
  color: #fff;
  font-size: 14px;
  letter-spacing: 1px;
}
</style>
