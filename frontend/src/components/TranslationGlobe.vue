<template>
  <div class="translation-globe" aria-hidden="true">
    <svg class="translation-globe__art" viewBox="0 0 820 470" fill="none">
      <defs>
        <linearGradient
          id="globe-sphere-fill"
          x1="205"
          y1="70"
          x2="580"
          y2="445"
          gradientUnits="userSpaceOnUse"
        >
          <stop stop-color="#173b9f" stop-opacity=".9" />
          <stop offset=".45" stop-color="#10255f" stop-opacity=".83" />
          <stop offset="1" stop-color="#061126" stop-opacity=".12" />
        </linearGradient>
        <radialGradient
          id="globe-sphere-shine"
          cx="0"
          cy="0"
          r="1"
          gradientUnits="userSpaceOnUse"
          gradientTransform="translate(383 168) rotate(96) scale(270 335)"
        >
          <stop stop-color="#4878ff" stop-opacity=".56" />
          <stop offset=".38" stop-color="#2442b4" stop-opacity=".22" />
          <stop offset="1" stop-color="#07142f" stop-opacity="0" />
        </radialGradient>
        <linearGradient
          id="globe-route-gradient"
          x1="87"
          y1="145"
          x2="730"
          y2="340"
          gradientUnits="userSpaceOnUse"
        >
          <stop stop-color="#30c6ff" />
          <stop offset=".52" stop-color="#3f78ff" />
          <stop offset="1" stop-color="#9d55ff" />
        </linearGradient>
        <pattern
          id="globe-dot-pattern"
          width="7"
          height="7"
          patternUnits="userSpaceOnUse"
        >
          <circle cx="1.6" cy="1.6" r="1.15" fill="#4e7dff" fill-opacity=".36" />
        </pattern>
        <clipPath id="globe-sphere-clip">
          <circle cx="382" cy="344" r="268" />
        </clipPath>
        <filter id="globe-soft-glow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="7" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <filter id="globe-node-glow" x="-300%" y="-300%" width="700%" height="700%">
          <feGaussianBlur stdDeviation="3.2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      <circle
        cx="382"
        cy="344"
        r="268"
        fill="url(#globe-sphere-fill)"
        stroke="#355fee"
        stroke-opacity=".32"
        stroke-width="1.4"
      />
      <circle cx="382" cy="344" r="268" fill="url(#globe-sphere-shine)" />

      <g clip-path="url(#globe-sphere-clip)" opacity=".9">
        <ellipse cx="382" cy="344" rx="268" ry="76" stroke="#3d65d9" stroke-opacity=".24" />
        <ellipse cx="382" cy="344" rx="268" ry="154" stroke="#3d65d9" stroke-opacity=".22" />
        <ellipse cx="382" cy="344" rx="268" ry="226" stroke="#3d65d9" stroke-opacity=".17" />
        <ellipse cx="382" cy="344" rx="92" ry="268" stroke="#3d65d9" stroke-opacity=".22" />
        <ellipse cx="382" cy="344" rx="180" ry="268" stroke="#3d65d9" stroke-opacity=".17" />
        <g fill="url(#globe-dot-pattern)" opacity=".92">
          <path d="M165 245c18-22 44-38 71-42l29 13 11 22 22 9 10 24-12 14-32-5-21 14-31-4-18-15-27-7-2-23Z" />
          <path d="M275 285c23 8 39 25 45 50l-7 34 13 36-10 39-23 30-14-22 3-38-17-38-2-39 12-52Z" />
          <path d="M365 215c28-25 61-41 99-43l29 17 41-2 38 20 25 29-4 24-31 5-24-12-24 7-6 26-26 14-16 35-30 18-19-16 10-33-20-24-9-30-24-15-39 2Z" />
          <path d="M456 322c20-7 43-3 58 9l4 25-13 25 8 31-22 39-31-4-20-23 4-33-13-25 25-44Z" />
          <path d="M589 351c18-9 44-8 62 3l16 21-13 18-36-2-19-15-10-25Z" />
        </g>
      </g>

      <path
        d="M91 328C214 114 349 83 477 285"
        stroke="url(#globe-route-gradient)"
        stroke-opacity=".9"
        stroke-width="1.35"
        filter="url(#globe-soft-glow)"
      />
      <path d="M138 403C272 210 429 187 624 369" stroke="url(#globe-route-gradient)" stroke-opacity=".73" stroke-width="1.2" />
      <path d="M260 432C358 224 531 191 720 318" stroke="url(#globe-route-gradient)" stroke-opacity=".67" stroke-width="1.1" />
      <path class="translation-globe__route" d="M108 312C258 196 392 201 557 352" stroke="url(#globe-route-gradient)" stroke-opacity=".55" stroke-width="1.25" />
      <path class="translation-globe__route" d="M311 438C397 270 503 239 681 384" stroke="url(#globe-route-gradient)" stroke-opacity=".5" stroke-width="1.2" />

      <g fill="#d9f1ff" filter="url(#globe-node-glow)">
        <circle class="translation-globe__node" cx="91" cy="328" r="3.2" />
        <circle class="translation-globe__node" cx="260" cy="432" r="3.1" style="animation-delay: .45s" />
        <circle class="translation-globe__node" cx="311" cy="217" r="3.2" style="animation-delay: .9s" />
        <circle class="translation-globe__node" cx="477" cy="285" r="3.2" style="animation-delay: 1.35s" />
        <circle class="translation-globe__node" cx="557" cy="352" r="3.2" style="animation-delay: 1.7s" />
        <circle class="translation-globe__node" cx="624" cy="369" r="3.2" style="animation-delay: .7s" />
        <circle class="translation-globe__node" cx="720" cy="318" r="3.2" style="animation-delay: 1.1s" />
      </g>
      <g stroke="#417fff" stroke-opacity=".43">
        <path d="M311 217V145" />
        <path d="M477 285V150" />
        <path d="M557 352V228" />
      </g>
      <g fill="#4a82ff" opacity=".76">
        <circle cx="311" cy="145" r="1.8" />
        <circle cx="477" cy="150" r="1.8" />
        <circle cx="557" cy="228" r="1.8" />
      </g>
    </svg>
    <span class="translation-globe__tag translation-globe__tag--transcribe">转写</span>
    <span class="translation-globe__tag translation-globe__tag--translate">翻译</span>
    <span class="translation-globe__tag translation-globe__tag--subtitle">字幕</span>
    <span class="translation-globe__tag translation-globe__tag--dubbing">配音</span>
  </div>
</template>
