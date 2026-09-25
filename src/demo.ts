import type {Invoice,CatalogItem,Alias,Audit,ExportRun} from './types';
export const catalog:CatalogItem[] = [
 {rms_item_id:'1004821',description:'Lumière Hydrating Serum 30ml',uom:'EA',supplier_id:'SUP-1042',unit_cost:78},
 {rms_item_id:'1004822',description:'Lumière Hydrating Serum 50ml',uom:'EA',supplier_id:'SUP-1042',unit_cost:112},
 {rms_item_id:'1004835',description:'Lumière Daily Moisturiser 50ml',uom:'EA',supplier_id:'SUP-1042',unit_cost:64},
 {rms_item_id:'1004840',description:'Lumière Gentle Cleanser 150ml',uom:'EA',supplier_id:'SUP-1042',unit_cost:42},
 {rms_item_id:'2001038',description:'Botanica Rosewater Mist 100ml',uom:'EA',supplier_id:'SUP-2016',unit_cost:38},
 {rms_item_id:'2001050',description:'Botanica Body Lotion 250ml',uom:'EA',supplier_id:'SUP-2016',unit_cost:46},
 {rms_item_id:'3002241',description:'Studio Colour Velvet Lipstick 04 Rose',uom:'EA',supplier_id:'SUP-3071',unit_cost:52},
 {rms_item_id:'3002242',description:'Studio Colour Velvet Lipstick 05 Coral',uom:'EA',supplier_id:'SUP-3071',unit_cost:52},
 {rms_item_id:'4001210',description:'Coast Mineral Sunscreen SPF50 50ml',uom:'EA',supplier_id:'SUP-4001',unit_cost:68},
 {rms_item_id:'4001220',description:'Coast After Sun Gel 100ml',uom:'EA',supplier_id:'SUP-4001',unit_cost:45},
];
function createInvoice(i:number):Invoice {
 const suppliers = [['Aster Beauty Trading','SUP-1042'],['Botanica Gulf','SUP-2016'],['Studio Colour Distribution','SUP-3071'],['Coast Care Middle East','SUP-4001']];
 const [name,supplier]=suppliers[i%4];const products=catalog.filter(c=>c.supplier_id===supplier).slice(0,i===0?3:2);
 const lines=products.map((p,j)=>({id:`line-${i}-${j}`,description:i===0&&j===0?'LUM HYDR SERUM 30 ML':p.description,quantity:24,unit_price:p.unit_cost!,line_total:24*p.unit_cost!,uom:'EA',tax_rate:5,rms_item_id:i===0&&j===0?null:p.rms_item_id,match_status:(i===0&&j===0?'suggested':'auto') as 'suggested'|'auto',confidence:i===0&&j===0?87:100,candidates:[{rms_item_id:p.rms_item_id,description:p.description,score:i===0&&j===0?87:100,reason:i===0&&j===0?'Abbreviation match · review required':'Exact item description'},...(i===0&&j===0?[{rms_item_id:'1004822',description:'Lumière Hydrating Serum 50ml',score:62,reason:'Different size · check source'}]:[])]}));
 const subtotal=lines.reduce((s,l)=>s+l.line_total,0);const tax=Math.round(subtotal*5)/100;
 return {id:`sample-${i+1}`,filename:`${name.split(' ')[0].toLowerCase()}_invoice_${20260081+i}.pdf`,supplier_id:supplier,supplier_name:name,supplier_site:'UAE-01',invoice_number:`INV-2026-${String(81+i).padStart(4,'0')}`,invoice_date:'2026-09-24',po_number:`PO-600${142+i}`,currency:'AED',subtotal,tax_total:tax,total:subtotal+tax,status:i===0||i===3||i===4?'needs_review':i===6?'exported':'ready',extraction_method:'Sample document',created_at:new Date(Date.UTC(2026,8,24,10,42-i*7)).toISOString(),updated_at:new Date().toISOString(),error:null,warnings:i===0?['One item description needs your confirmation.']:[],version:1,pages:1,lines,raw_text:'Fictional sample data for the interactive preview. Open the document view to inspect the example.'};
}
type DemoState={invoices:Invoice[];aliases:Alias[];exports:ExportRun[];audit:Record<string,Audit[]>};
const key='invoice-studio-preview-v1';
let volatileState:DemoState|undefined;
function initial():DemoState{return {invoices:Array.from({length:7},(_,i)=>createInvoice(i)),aliases:[],exports:[],audit:{}};}
export function loadDemo():DemoState {try{return JSON.parse(localStorage.getItem(key)||'null')||volatileState||initial();}catch{return volatileState||(volatileState=initial());}}
export function saveDemo(d:DemoState){volatileState=structuredClone(d);try{localStorage.setItem(key,JSON.stringify(d));}catch{/* Preview remains usable without storage. */}}
export function resetDemo(){saveDemo(initial());}
export function originalSample(id:string){const n=Number(id.replace('sample-',''))-1;return Number.isInteger(n)&&n>=0&&n<7?createInvoice(n):null;}
