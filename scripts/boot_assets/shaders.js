window.VERT = `
attribute vec2 a;
void main() {
  gl_Position = vec4(a, 0.0, 1.0);
}`;

window.FRAG = `
precision highp float;

uniform vec2 uRes;
uniform float uTime;
uniform float uSteps;
uniform float uDin;
uniform float uDout;
uniform float uDisk;
uniform float uStars;
uniform float uRot;
uniform float uDebug;
uniform vec3 uCam;
uniform vec3 uTarget;

float hash31(vec3 p) {
  p = fract(p * 0.1031);
  p += dot(p, p.yzx + 33.33);
  return fract((p.x + p.y) * p.z);
}

float valueNoise(vec3 p) {
  vec3 cell = floor(p);
  vec3 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float n000 = hash31(cell + vec3(0.0, 0.0, 0.0));
  float n100 = hash31(cell + vec3(1.0, 0.0, 0.0));
  float n010 = hash31(cell + vec3(0.0, 1.0, 0.0));
  float n110 = hash31(cell + vec3(1.0, 1.0, 0.0));
  float n001 = hash31(cell + vec3(0.0, 0.0, 1.0));
  float n101 = hash31(cell + vec3(1.0, 0.0, 1.0));
  float n011 = hash31(cell + vec3(0.0, 1.0, 1.0));
  float n111 = hash31(cell + vec3(1.0, 1.0, 1.0));
  float z0 = mix(mix(n000, n100, f.x), mix(n010, n110, f.x), f.y);
  float z1 = mix(mix(n001, n101, f.x), mix(n011, n111, f.x), f.y);
  return mix(z0, z1, f.z);
}

float fbm5(vec3 p) {
  float sum = 0.0;
  float amp = 0.5;
  for (int octave = 0; octave < 5; octave++) {
    sum += amp * valueNoise(p);
    p = p * 2.03 + vec3(1.3);
    amp *= 0.5;
  }
  return sum;
}

vec3 starfield(vec3 dir) {
  vec3 color = vec3(0.008, 0.012, 0.03);
  vec3 normal = normalize(vec3(0.25, 1.0, 0.15));
  float band = exp(-pow(dot(dir, normal), 2.0) * 7.0);
  vec3 galaxyA = vec3(0.04, 0.07, 0.20);
  vec3 galaxyB = vec3(0.42, 0.24, 0.52);
  color += mix(galaxyA, galaxyB, fbm5(dir * 5.0)) * band * 0.55;
  vec3 ad = abs(dir);
  vec2 sky = dir.xy / max(ad.x + ad.y + ad.z, 0.0001);
  if (dir.z < 0.0) {
    vec2 oldSky = sky;
    sky = (1.0 - abs(oldSky.yx)) * sign(oldSky.xy);
  }
  for (int layer = 0; layer < 4; layer++) {
    float layerF = float(layer);
    float scale = 82.0 + layerF * 61.0;
    float angle = layerF * 0.71;
    mat2 rotation = mat2(cos(angle), -sin(angle), sin(angle), cos(angle));
    vec2 grid = rotation * sky * scale;
    vec2 cell = floor(grid);
    vec2 local = fract(grid) - 0.5;
    float seed = hash31(vec3(cell, layerF + 4.0));
    float enabled = smoothstep(0.985 + layerF * 0.0025, 1.0, seed);
    float radius = mix(0.075, 0.16, hash31(vec3(cell + 17.0, layerF)));
    float circle = 1.0 - smoothstep(radius * 0.55, radius, length(local));
    float star = enabled * circle;
    vec3 warm = vec3(1.0, 0.72, 0.45);
    vec3 cool = vec3(0.62, 0.80, 1.0);
    color += star * mix(warm, cool, hash31(vec3(cell + 9.0, layerF))) * 1.45;
  }
  return color * uStars;
}

float segmentDistance(vec2 p, vec2 a, vec2 b) {
  vec2 pa = p - a;
  vec2 ba = b - a;
  float h = clamp(dot(pa, ba) / max(dot(ba, ba), 0.0001), 0.0, 1.0);
  return length(pa - ba * h);
}

vec2 graphNode(float id, float time) {
  float angle = hash31(vec3(id, 2.7, 9.1)) * 6.2831853;
  float speed = mix(0.018, 0.040, hash31(vec3(id, 4.3, 1.7)));
  float phase = fract(hash31(vec3(id, 7.9, 3.2)) - time * speed);
  float radius = mix(0.06, 1.32, phase);
  float bend = (1.0 - phase) * (1.0 - phase) * 0.55;
  angle += bend * mix(-1.0, 1.0, step(0.5, hash31(vec3(id, 5.1, 6.6))));
  return vec2(cos(angle), sin(angle)) * radius;
}

vec3 infallGraph(vec2 p, float time, float layerOffset) {
  float nodeGlow = 0.0;
  float links = 0.0;
  for (int nodeIndex = 0; nodeIndex < 34; nodeIndex++) {
    float id = float(nodeIndex) + layerOffset;
    vec2 node = graphNode(id, time);
    float radialFade = smoothstep(0.055, 0.16, length(node));
    radialFade *= smoothstep(1.35, 1.05, length(node));
    float d = length(p - node);
    nodeGlow += exp(-d * d * 8500.0) * radialFade;
    nodeGlow += exp(-d * d * 620.0) * 0.22 * radialFade;
    if (hash31(vec3(id, 8.0, 2.0)) > 0.38) {
      float nextId = mod(float(nodeIndex) + 3.0, 34.0) + layerOffset;
      vec2 nextNode = graphNode(nextId, time);
      float separation = length(node - nextNode);
      float lineGate = smoothstep(0.48, 0.16, separation);
      float lineD = segmentDistance(p, node, nextNode);
      links += smoothstep(0.0032, 0.0005, lineD) * lineGate * radialFade;
    }
  }
  vec3 cyan = vec3(0.18, 0.62, 0.86);
  vec3 violet = vec3(0.35, 0.22, 0.68);
  return mix(violet, cyan, smoothstep(-0.6, 0.7, p.x)) * (nodeGlow * 0.72 + links * 0.095);
}

vec3 heatColor(float temperature) {
  vec3 darkRed = vec3(0.55, 0.06, 0.01);
  vec3 orange = vec3(1.0, 0.42, 0.10);
  vec3 warmWhite = vec3(1.0, 0.86, 0.55);
  vec3 blueWhite = vec3(0.85, 0.92, 1.25);
  vec3 color = mix(darkRed, orange, smoothstep(0.0, 0.55, temperature));
  color = mix(color, warmWhite, smoothstep(0.50, 1.05, temperature));
  return mix(color, blueWhite, smoothstep(1.05, 1.90, temperature));
}

void main() {
  vec2 pixel = (gl_FragCoord.xy - 0.5 * uRes) / uRes.y;
  vec3 rayOrigin = uCam;
  vec3 forward = normalize(uTarget - rayOrigin);
  vec3 worldUp = vec3(0.0, 1.0, 0.0);
  if (abs(forward.y) > 0.98) worldUp = vec3(0.0, 0.0, 1.0);
  vec3 right = normalize(cross(forward, worldUp));
  vec3 up = cross(right, forward);
  vec3 rayDir = normalize(pixel.x * right + pixel.y * up + 1.8 * forward);
  vec3 position = rayOrigin;
  vec3 color = vec3(0.0);
  float transmission = 1.0;
  float minRadius = 10000.0;
  float lastRadius = length(rayOrigin);
  float crossings = 0.0;

  for (int stepIndex = 0; stepIndex < 600; stepIndex++) {
    if (float(stepIndex) >= uSteps) break;
    float radius = max(length(position), 0.001);
    minRadius = min(minRadius, radius);
    if (radius < 1.03) {
      transmission = 0.0;
      break;
    }
    if (radius > 48.0 && dot(position, rayDir) > 0.0) break;

    vec3 angularMomentum = cross(position, rayDir);
    float h2 = dot(angularMomentum, angularMomentum);
    float r2 = radius * radius;
    vec3 acceleration = -1.5 * h2 * position / max(r2 * r2 * radius, 0.00001);
    float farMix = smoothstep(6.0, 20.0, radius);
    float dt = max(0.012, radius * mix(0.02, 0.06, farMix));

    float diskHeight = mix(0.22, 2.8, smoothstep(7.0, uDout, radius));
    float planeFog = exp(-abs(position.y) / max(diskHeight, 0.05) * 2.2);
    float fogInner = smoothstep(5.0, 15.0, radius);
    float fogOuter = smoothstep(uDout + 9.0, uDout - 13.0, radius);
    float fogDensity = planeFog * fogInner * fogOuter * 0.0065;
    float purpleMix = smoothstep(12.0, uDout, radius);
    vec3 innerMist = vec3(0.055, 0.028, 0.018);
    vec3 outerMist = vec3(0.075, 0.028, 0.135);
    vec3 mistColor = mix(innerMist, outerMist, purpleMix);
    color += transmission * mistColor * fogDensity * dt * uDisk;

    rayDir = normalize(rayDir + acceleration * dt);
    vec3 nextPosition = position + rayDir * dt;

    if (position.y * nextPosition.y <= 0.0) {
      float crossT = abs(position.y) / (abs(position.y) + abs(nextPosition.y) + 0.00001);
      vec3 hit = mix(position, nextPosition, crossT);
      float diskRadius = length(hit.xz);
      if (diskRadius > uDin && diskRadius < uDout) {
        crossings += 1.0;
        float safeRadius = max(diskRadius, 3.001);
        float flux = pow(safeRadius / 3.0, -3.0) * (1.0 - sqrt(3.0 / safeRadius));
        float temperature = pow(max(flux * 10.0, 0.0), 0.25);
        float angle = atan(hit.z, hit.x);
        float omega = uRot * pow(3.0 / diskRadius, 1.5);
        vec2 swirl = vec2(cos(angle + uTime * omega), sin(angle + uTime * omega));
        float pattern = fbm5(vec3(hit.xz * 0.42 + swirl * 2.0, uTime * 0.04));
        float intensity = flux * 15.0 + exp(-pow((diskRadius - 3.1) * 3.0, 2.0)) * 2.8;
        intensity *= mix(0.35, 1.3, pattern);
        float outerFade = smoothstep(uDout, uDout - 18.0, diskRadius);
        float innerFade = smoothstep(uDin, uDin + 0.65, diskRadius);
        intensity *= outerFade * innerFade;
        vec3 tangent = normalize(vec3(-sin(angle), 0.0, cos(angle)));
        float beta = sqrt(0.5 / diskRadius);
        float gamma = 1.0 / sqrt(max(1.0 - beta * beta, 0.001));
        float doppler = 1.0 / (gamma * (1.0 - dot(tangent * beta, rayDir)));
        doppler = clamp(doppler, 0.5, 1.85);
        float redshift = sqrt(max(1.0 - 1.0 / diskRadius, 0.0));
        float opacity = mix(0.72, 0.88, smoothstep(13.0, 4.0, diskRadius));
        opacity *= mix(0.35, 1.0, outerFade);
        vec3 emission = heatColor(temperature * doppler * redshift) * intensity;
        color += transmission * opacity * emission * doppler * doppler * redshift * uDisk;
        transmission *= 1.0 - opacity;
        if (transmission < 0.02) break;
      }
    }
    position = nextPosition;
    lastRadius = radius;
  }

  if (transmission > 0.0) {
    float edgeDim = clamp((lastRadius - 1.03) * 0.45, 0.45, 1.0);
    float shadowClearance = smoothstep(2.05, 2.45, minRadius);
    vec3 deepSpace = starfield(rayDir) * mix(0.14, 1.0, shadowClearance);
    float lensBridge = (1.0 - shadowClearance) * smoothstep(1.08, 1.92, minRadius);
    deepSpace += vec3(0.024, 0.012, 0.052) * lensBridge;
    float graphMask = smoothstep(1.45, 1.85, minRadius);
    color += transmission * deepSpace * edgeDim;
    color += transmission * infallGraph(pixel, uTime, 0.0) * graphMask * 0.72;
  }

  float viewSide = sign(uCam.y);
  if (abs(viewSide) < 0.1) viewSide = 1.0;
  float farSide = smoothstep(-0.28, 0.28, -pixel.y * viewSide);
  float ringRadius = mix(1.48, 1.67, farSide);
  float ringWidth = mix(18.0, 6.5, farSide);
  float photonRing = exp(-pow((minRadius - ringRadius) * ringWidth, 2.0));
  float fineOutline = exp(-pow((minRadius - 1.10) * 30.0, 2.0));
  vec3 gold = vec3(1.28, 0.78, 0.22);
  color += gold * (fineOutline * 0.22 + photonRing * mix(0.10, 0.34, farSide));

  float frontCenterFade = smoothstep(0.055, 0.16, length(pixel));
  float frontEdgeFade = smoothstep(1.28, 0.92, length(pixel));
  vec3 foregroundGraph = infallGraph(pixel * 1.07, uTime * 1.06, 47.0);
  color += foregroundGraph * frontCenterFade * frontEdgeFade * 0.46;

  if (uDebug > 0.5) {
    if (uDebug < 1.5) color = color - starfield(rayDir);
    else if (uDebug < 2.5) color = starfield(rayDir);
    else color = vec3(minRadius / 12.0, crossings / 4.0, 0.0);
  }

  vec3 mapped = color * 0.95;
  mapped = clamp((mapped * (2.51 * mapped + 0.03)) / (mapped * (2.43 * mapped + 0.59) + 0.14), 0.0, 1.0);
  float vignette = smoothstep(1.3, 0.3, length(pixel) * 1.15);
  mapped *= mix(0.52, 1.0, vignette);
  float grain = hash31(vec3(gl_FragCoord.xy, fract(uTime * 13.7) * 97.0)) - 0.5;
  mapped += grain * 0.025;
  gl_FragColor = vec4(mapped, 1.0);
}`;
