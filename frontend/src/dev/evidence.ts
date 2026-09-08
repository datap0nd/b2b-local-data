import {toCanvas} from 'html-to-image';

export async function captureElement(element: HTMLElement): Promise<HTMLCanvasElement[]> {
  await document.fonts.ready;
  const width = Math.ceil(element.getBoundingClientRect().width);
  const height = Math.ceil(Math.max(element.scrollHeight, element.getBoundingClientRect().height));
  if (!width || !height) throw new Error('The evidence surface has no dimensions.');
  const tiles: HTMLCanvasElement[] = [];
  for (let top = 0; top < height; top += 2048) {
    const tileHeight = Math.min(2048, height - top);
    // Clone directly from the laid-out production element. Moving a DOM clone
    // outside the app before computing styles loses inherited CSS variables.
    tiles.push(await toCanvas(element, {width, height: tileHeight, pixelRatio: 1, backgroundColor: '#ffffff',
      style: {margin: '0', position: 'relative', left: '0', top: `${-top}px`, maxHeight: 'none', overflow: 'visible'}}));
  }
  return tiles;
}

export async function scenarioPng(title: string, notes: string[], tiles: HTMLCanvasElement[]): Promise<Blob> {
  const width = Math.max(1200, ...tiles.map(t => t.width));
  const lines = [title, 'Actual rendered responses · bounded previews · full data checked separately', ...notes]
    .flatMap(text => text.match(/.{1,125}/g) ?? ['']);
  const header = lines.length * 24 + 36;
  const height = header + tiles.reduce((sum, tile) => sum + tile.height + 16, 0);
  if (height > 32760 || width * height > 80_000_000) throw new Error('Scenario evidence exceeds the readable PNG size limit; its turns remain saved for capture retry.');
  const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
  const ctx = canvas.getContext('2d'); if (!ctx) throw new Error('Canvas is unavailable.');
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, width, height); ctx.fillStyle = '#172033'; ctx.font = '16px sans-serif';
  lines.forEach((line, i) => ctx.fillText(line, 20, 28 + i * 24));
  let y = header;
  for (const tile of tiles) { ctx.drawImage(tile, 0, y); y += tile.height + 16; }
  return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('PNG encoding failed.')), 'image/png'));
}
