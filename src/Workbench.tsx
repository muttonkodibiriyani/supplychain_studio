import {useCallback,useEffect,useState} from 'react';
import {AlertTriangle,ArrowRight,Clock3,Gauge,ListFilter,RefreshCw} from 'lucide-react';
import * as api from './api';
import {Empty,StatusBadge,dateLabel} from './components';
import {OWNER_LABELS} from './reasonCodes';
import type {ExceptionQueue,Kpis} from './types';

export function ageLabel(seconds:number|null|undefined):string{
 if(seconds==null||!Number.isFinite(seconds))return '—';
 const s=Math.max(0,Math.floor(seconds));
 if(s<60)return `${s} s`;const m=Math.floor(s/60);if(m<60)return `${m} min`;const h=Math.floor(m/60);if(h<48)return `${h} h ${m%60} min`;const d=Math.floor(h/24);return `${d} d ${h%24} h`;
}
function ownerLabel(owner:string){return OWNER_LABELS[owner]||owner.replaceAll('_',' ');}
function Ratio({label,ratio,hint}:{label:string;ratio:{numerator:number;denominator:number;definition:string};hint:string}){
 return <div className="stat-card" title={ratio.definition}><div><span>{label}</span><span className="stat-icon"><Gauge size={18}/></span></div><strong>{ratio.numerator.toLocaleString()} of {ratio.denominator.toLocaleString()}</strong><small>{hint}</small></div>;
}
export function Workbench({onOpen,notify}:{onOpen:(id:string)=>void;notify:(m:string,error?:boolean)=>void}){
 const [queue,setQueue]=useState<ExceptionQueue|null>(null);const [kpis,setKpis]=useState<Kpis|null>(null);const [error,setError]=useState('');const [busy,setBusy]=useState(false);
 const load=useCallback(async()=>{setBusy(true);try{const [q,k]=await Promise.all([api.exceptions(),api.kpis()]);setQueue(q);setKpis(k);setError('');}catch(e){setError((e as Error).message);}finally{setBusy(false);}},[]);
 useEffect(()=>{void load();},[load]);
 return <>
 <div className="page-heading"><div><div className="eyebrow">WHO OWNS THE NEXT ACTION</div><h1>Exception workbench<span className="heading-dot">.</span></h1><p>Every held invoice grouped by its governed reason code, with the role that owns it and how long it has waited.</p></div><div className="button-row"><button className="btn" onClick={()=>void load()} disabled={busy}><RefreshCw size={16} className={busy?'spin':''}/> Refresh</button><button className="btn" onClick={()=>api.downloadExceptions().then(n=>notify(`${n.toLocaleString()} exception${n===1?'':'s'} downloaded.`)).catch(e=>notify((e as Error).message,true))}>Download exceptions CSV</button></div></div>
 {error&&<p className="error-banner" role="alert">{error}</p>}
 {kpis&&<section className="stats-grid" aria-label="Control KPIs">
  <Ratio label="K1 · Touchless" ratio={kpis.k1_touchless} hint="Reached ready or exported with no human correction, over all invoices"/>
  <Ratio label="K2 · First-time match" ratio={kpis.k2_first_time_match} hint="Every line matched automatically at first extraction, over extracted invoices"/>
  <div className="stat-card" title={kpis.k3_cycle_time.definition}><div><span>K3 · Cycle time (median)</span><span className="stat-icon"><Clock3 size={18}/></span></div><strong>{kpis.k3_cycle_time.median_seconds==null?'—':ageLabel(kpis.k3_cycle_time.median_seconds)}</strong><small>{kpis.k3_cycle_time.n.toLocaleString()} invoice{kpis.k3_cycle_time.n===1?'':'s'} reached ready · upload to first ready</small></div>
 </section>}
 {kpis?.contains_demo_data&&<div className="callout muted-callout"><AlertTriangle size={20}/><div><strong>Fictional sample data is included</strong><p>These figures describe the sample workspace, not a measured corpus.</p></div></div>}
 {queue&&<p className="inline-note">{queue.invoices_with_exceptions.toLocaleString()} of {queue.invoices_total.toLocaleString()} invoices carry at least one reason code · snapshot {dateLabel(queue.as_of)}</p>}
 {queue&&!queue.groups.length&&<section className="panel"><Empty title="No open exceptions" icon={<ListFilter size={32}/>}><p>Every invoice in this workspace is either in flight or eligible for export.</p></Empty></section>}
 {queue?.groups.map(g=><section className="panel" key={g.code} data-reason-code={g.code}><div className="worklist-title"><div><h2><code>{g.code}</code> <span>{g.count.toLocaleString()}</span></h2><p>{g.message}</p></div><div className="button-row"><span className="tag">{ownerLabel(g.owner)}</span><span className="tag">{g.level==='line'?'line level':'invoice level'}</span><span className="amber-text">Oldest {ageLabel(g.oldest_age_seconds)}</span></div></div>
  <div className="table-scroll"><table><thead><tr><th>Invoice</th><th>Supplier</th><th>Status</th><th>Waiting</th><th>Also flagged</th><th></th></tr></thead><tbody>{g.invoices.map(i=><tr key={i.id}><td><button className="invoice-link" onClick={()=>onOpen(i.id)} aria-label={`Open ${i.invoice_number||i.filename}`}><span><strong>{i.invoice_number||'No number yet'}</strong><br/><small className="muted">{i.filename}</small></span></button></td><td>{i.supplier_name||i.supplier_id||'—'}</td><td><StatusBadge status={i.status}/></td><td>{ageLabel(i.age_seconds)}</td><td>{i.reason_codes.filter(c=>c!==g.code).map(c=><span className="id-chip" key={c}>{c}</span>)}{g.code==='duplicate_suspected'&&i.duplicate_of.length>0&&<small className="muted"> · same as {i.duplicate_of.join(', ')}</small>}</td><td><button className="icon-btn" aria-label={`Review ${i.invoice_number||i.filename}`} onClick={()=>onOpen(i.id)}><ArrowRight size={16}/></button></td></tr>)}</tbody></table></div>
  {g.truncated&&<p className="inline-note">Showing the oldest {g.invoices.length.toLocaleString()} of {g.count.toLocaleString()}. Download the exceptions CSV for the full list.</p>}
 </section>)}
 {queue&&<section className="panel"><div className="worklist-title"><div><h2>Reason codes and owners</h2><p>The governed list every exception maps onto. Unknown codes are a defect, not a category.</p></div></div><div className="table-scroll"><table><thead><tr><th>Code</th><th>Owner</th><th>Meaning</th></tr></thead><tbody>{queue.registry.map(r=><tr key={r.code}><td><code>{r.code}</code></td><td>{ownerLabel(r.owner)}</td><td>{r.message}</td></tr>)}</tbody></table></div></section>}
 </>;
}
