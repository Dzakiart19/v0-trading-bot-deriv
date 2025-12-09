"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { DigitHeatmap } from "@/components/digit-heatmap"
import { type DerivAPI, type TickData, createDerivAPI } from "@/lib/deriv-api"
import { getLastDigit } from "@/lib/indicators"
import { ArrowLeft, Wifi, WifiOff, Play, Square, Target, Settings2 } from "lucide-react"

const SYMBOLS = [
  { value: "R_10", label: "Volatility 10" },
  { value: "R_25", label: "Volatility 25" },
  { value: "R_50", label: "Volatility 50" },
  { value: "R_75", label: "Volatility 75" },
  { value: "R_100", label: "Volatility 100" },
]

type ContractType = "DIGITEVEN" | "DIGITODD" | "DIGITMATCH" | "DIGITDIFF" | "DIGITOVER" | "DIGITUNDER"

interface TradeHistory {
  id: number
  type: string
  digit?: number
  amount: number
  profit: number
  status: "won" | "lost" | "open"
}

export default function DigitPadPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [api, setApi] = useState<DerivAPI | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [symbol, setSymbol] = useState("R_100")
  const [ticks, setTicks] = useState<TickData[]>([])
  const [balance, setBalance] = useState(0)
  const [currency, setCurrency] = useState("USD")
  const [totalProfit, setTotalProfit] = useState(0)
  const [winRate, setWinRate] = useState(0)

  // Auto trading state
  const [isAutoRunning, setIsAutoRunning] = useState(false)
  const [isTrading, setIsTrading] = useState(false)
  const [stake, setStake] = useState(1)
  const [contractType, setContractType] = useState<ContractType>("DIGITEVEN")
  const [martingale, setMartingale] = useState(true)
  const [martingaleLevel, setMartingaleLevel] = useState(0)
  const [targetProfit, setTargetProfit] = useState(10)
  const [stopLoss, setStopLoss] = useState(20)
  const [showSettings, setShowSettings] = useState(false)
  const [trades, setTrades] = useState<TradeHistory[]>([])

  // Stats
  const [lastDigits, setLastDigits] = useState<number[]>([])
  const [prediction, setPrediction] = useState<{ type: string; digit?: number; confidence: number } | null>(null)

  // Refs for async callbacks
  const autoRunningRef = useRef(false)
  const martingaleLevelRef = useRef(0)
  const totalProfitRef = useRef(0)

  useEffect(() => {
    const token = localStorage.getItem("deriv_token")
    if (!token) {
      router.push("/")
      return
    }

    const derivApi = createDerivAPI(token)
    derivApi
      .connect()
      .then(() => {
        setApi(derivApi)
        setIsConnected(true)

        derivApi.getBalance().then(({ balance, currency }) => {
          setBalance(balance)
          setCurrency(currency)
        })

        derivApi.getTickHistory(symbol, 100).then((history) => {
          setTicks(history)
          setLastDigits(history.map((t) => getLastDigit(t.quote)))
        })

        derivApi.subscribeTicks(symbol, (tick) => {
          setTicks((prev) => [...prev.slice(-99), tick])
          setLastDigits((prev) => [...prev.slice(-99), getLastDigit(tick.quote)])
        })

        // Auto start if param is set
        if (searchParams.get("auto") === "true") {
          setTimeout(() => {
            setIsAutoRunning(true)
            autoRunningRef.current = true
          }, 2000)
        }
      })
      .catch(() => {
        router.push("/")
      })

    return () => {
      derivApi.disconnect()
    }
  }, [router, searchParams])

  useEffect(() => {
    if (!api || !isConnected) return

    api.unsubscribeTicks(symbol).then(() => {
      api.getTickHistory(symbol, 100).then((history) => {
        setTicks(history)
        setLastDigits(history.map((t) => getLastDigit(t.quote)))
      })
      api.subscribeTicks(symbol, (tick) => {
        setTicks((prev) => [...prev.slice(-99), tick])
        setLastDigits((prev) => [...prev.slice(-99), getLastDigit(tick.quote)])
      })
    })
  }, [symbol, api, isConnected])

  // Analyze digits and auto trade
  useEffect(() => {
    if (lastDigits.length < 20) return

    const recent = lastDigits.slice(-50)
    const evenCount = recent.filter((d) => d % 2 === 0).length
    const oddCount = recent.length - evenCount

    // Frequency analysis
    const freq = new Map<number, number>()
    for (let i = 0; i <= 9; i++) freq.set(i, 0)
    for (const d of recent) freq.set(d, (freq.get(d) || 0) + 1)

    const entries = Array.from(freq.entries())
    entries.sort((a, b) => b[1] - a[1])
    const hotDigit = entries[0][0]
    const coldDigit = entries[entries.length - 1][0]

    // Determine prediction
    let newPrediction: typeof prediction = null
    const evenPct = (evenCount / recent.length) * 100

    if (contractType === "DIGITEVEN" || contractType === "DIGITODD") {
      if (evenPct > 55) {
        newPrediction = { type: "EVEN", confidence: Math.min(evenPct, 85) }
      } else if (evenPct < 45) {
        newPrediction = { type: "ODD", confidence: Math.min(100 - evenPct, 85) }
      } else {
        newPrediction = { type: evenCount > oddCount ? "EVEN" : "ODD", confidence: 60 }
      }
    } else if (contractType === "DIGITMATCH") {
      newPrediction = {
        type: "MATCH",
        digit: hotDigit,
        confidence: Math.min((freq.get(hotDigit)! / recent.length) * 100 * 2, 80),
      }
    } else if (contractType === "DIGITDIFF") {
      newPrediction = {
        type: "DIFFER",
        digit: coldDigit,
        confidence: Math.min((1 - freq.get(coldDigit)! / recent.length) * 100, 90),
      }
    } else if (contractType === "DIGITOVER") {
      const overCount = recent.filter((d) => d > 4).length
      newPrediction = {
        type: "OVER",
        digit: 4,
        confidence: Math.min((overCount / recent.length) * 100, 85),
      }
    } else if (contractType === "DIGITUNDER") {
      const underCount = recent.filter((d) => d < 5).length
      newPrediction = {
        type: "UNDER",
        digit: 5,
        confidence: Math.min((underCount / recent.length) * 100, 85),
      }
    }

    setPrediction(newPrediction)

    // Auto execute trade
    if (autoRunningRef.current && !isTrading && newPrediction && newPrediction.confidence >= 65) {
      executeTrade(newPrediction)
    }
  }, [lastDigits, contractType])

  const executeTrade = useCallback(
    async (pred: NonNullable<typeof prediction>) => {
      if (!api || isTrading) return

      // Check limits
      if (totalProfitRef.current >= targetProfit || totalProfitRef.current <= -stopLoss) {
        setIsAutoRunning(false)
        autoRunningRef.current = false
        return
      }

      setIsTrading(true)

      try {
        let currentStake = stake
        if (martingale && martingaleLevelRef.current > 0) {
          currentStake = stake * Math.pow(2, martingaleLevelRef.current)
        }
        currentStake = Math.min(currentStake, balance * 0.2)

        const params: any = {
          contract_type: contractType,
          symbol,
          duration: 5,
          duration_unit: "t",
          amount: currentStake,
          basis: "stake",
        }

        if (pred.digit !== undefined) {
          params.barrier = pred.digit.toString()
        }

        const proposal = await api.getProposal(params)
        const result = await api.buyContract(proposal.id, proposal.ask_price)

        const newTrade: TradeHistory = {
          id: result.contract_id,
          type: pred.type,
          digit: pred.digit,
          amount: currentStake,
          profit: 0,
          status: "open",
        }

        setTrades((prev) => [newTrade, ...prev.slice(0, 49)])

        const { balance: newBalance } = await api.getBalance()
        setBalance(newBalance)

        // Monitor result
        const checkResult = setInterval(async () => {
          try {
            const update = await api.getContractUpdate(result.contract_id)
            if (update.status !== "open") {
              clearInterval(checkResult)

              setTrades((prev) =>
                prev.map((t) =>
                  t.id === result.contract_id ? { ...t, profit: update.profit, status: update.status } : t,
                ),
              )

              const newProfit = totalProfitRef.current + update.profit
              totalProfitRef.current = newProfit
              setTotalProfit(newProfit)

              if (update.status === "won") {
                martingaleLevelRef.current = 0
                setMartingaleLevel(0)
              } else if (martingale) {
                martingaleLevelRef.current = Math.min(martingaleLevelRef.current + 1, 5)
                setMartingaleLevel(martingaleLevelRef.current)
              }

              setTrades((prev) => {
                const completed = prev.filter((t) => t.status !== "open")
                const wins = completed.filter((t) => t.status === "won").length
                setWinRate(completed.length > 0 ? (wins / completed.length) * 100 : 0)
                return prev
              })

              const { balance: finalBalance } = await api.getBalance()
              setBalance(finalBalance)
              setIsTrading(false)
            }
          } catch {
            clearInterval(checkResult)
            setIsTrading(false)
          }
        }, 1000)
      } catch (error) {
        console.error("Trade error:", error)
        setIsTrading(false)
      }
    },
    [api, stake, symbol, contractType, martingale, balance, targetProfit, stopLoss, isTrading],
  )

  const toggleAutoTrading = () => {
    const newState = !isAutoRunning
    setIsAutoRunning(newState)
    autoRunningRef.current = newState
    if (!newState) {
      martingaleLevelRef.current = 0
      setMartingaleLevel(0)
    }
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border bg-card sticky top-0 z-10">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" onClick={() => router.push("/")}>
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div>
              <h1 className="text-lg font-bold">DigitPad Strategy</h1>
              <p className="text-xs text-muted-foreground">Digit Frequency Auto Trading</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              {isConnected ? <Wifi className="h-4 w-4 text-green-500" /> : <WifiOff className="h-4 w-4 text-red-500" />}
            </div>
            <div className="text-right">
              <div className="font-semibold">
                {balance.toFixed(2)} {currency}
              </div>
              <div className={`text-xs ${totalProfit >= 0 ? "text-green-500" : "text-red-500"}`}>
                {totalProfit >= 0 ? "+" : ""}
                {totalProfit.toFixed(2)}
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-4">
        {/* Auto Trading Status */}
        <Card className={`mb-4 ${isAutoRunning ? "border-green-500/50 bg-green-500/10" : ""}`}>
          <CardContent className="py-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {isAutoRunning && <div className="h-3 w-3 bg-green-500 rounded-full animate-pulse"></div>}
                <span className={`font-semibold ${isAutoRunning ? "text-green-400" : "text-muted-foreground"}`}>
                  {isAutoRunning ? "Auto Trading Active" : "Auto Trading Stopped"}
                </span>
                {isTrading && <Badge className="bg-yellow-600">Trading...</Badge>}
                {martingaleLevel > 0 && <Badge className="bg-orange-600">M{martingaleLevel}</Badge>}
              </div>
              <div className="flex items-center gap-2">
                <Button variant="ghost" size="sm" onClick={() => setShowSettings(!showSettings)}>
                  <Settings2 className="h-4 w-4" />
                </Button>
                <Button
                  size="sm"
                  onClick={toggleAutoTrading}
                  className={isAutoRunning ? "bg-red-600 hover:bg-red-700" : "bg-green-600 hover:bg-green-700"}
                >
                  {isAutoRunning ? (
                    <>
                      <Square className="h-4 w-4 mr-2" />
                      STOP
                    </>
                  ) : (
                    <>
                      <Play className="h-4 w-4 mr-2" />
                      START
                    </>
                  )}
                </Button>
              </div>
            </div>

            {showSettings && (
              <div className="mt-4 pt-4 border-t border-border grid grid-cols-2 md:grid-cols-5 gap-4">
                <div className="space-y-1">
                  <Label className="text-xs">Contract Type</Label>
                  <Select value={contractType} onValueChange={(v) => setContractType(v as ContractType)}>
                    <SelectTrigger className="bg-input">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="DIGITEVEN">Even</SelectItem>
                      <SelectItem value="DIGITODD">Odd</SelectItem>
                      <SelectItem value="DIGITMATCH">Matches</SelectItem>
                      <SelectItem value="DIGITDIFF">Differs</SelectItem>
                      <SelectItem value="DIGITOVER">Over</SelectItem>
                      <SelectItem value="DIGITUNDER">Under</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Stake ($)</Label>
                  <Input
                    type="number"
                    value={stake}
                    onChange={(e) => setStake(Number(e.target.value) || 1)}
                    className="bg-input"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Target ($)</Label>
                  <Input
                    type="number"
                    value={targetProfit}
                    onChange={(e) => setTargetProfit(Number(e.target.value) || 10)}
                    className="bg-input"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Stop Loss ($)</Label>
                  <Input
                    type="number"
                    value={stopLoss}
                    onChange={(e) => setStopLoss(Number(e.target.value) || 20)}
                    className="bg-input"
                  />
                </div>
                <div className="flex items-center justify-between p-2 bg-input rounded">
                  <Label className="text-xs">Martingale</Label>
                  <Switch checked={martingale} onCheckedChange={setMartingale} />
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 space-y-4">
            {/* Symbol & Price */}
            <div className="flex items-center gap-4">
              <Select value={symbol} onValueChange={setSymbol}>
                <SelectTrigger className="w-[200px] bg-card">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SYMBOLS.map((s) => (
                    <SelectItem key={s.value} value={s.value}>
                      {s.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {ticks.length > 0 && (
                <div className="text-2xl font-mono font-bold">
                  {ticks[ticks.length - 1]?.quote.toFixed(5)}
                  <span className="ml-2 text-3xl text-primary">
                    {getLastDigit(ticks[ticks.length - 1]?.quote || 0)}
                  </span>
                </div>
              )}
            </div>

            {/* Digit Heatmap */}
            <Card className="bg-card">
              <CardHeader className="py-3">
                <CardTitle className="text-sm">Digit Frequency Heatmap</CardTitle>
              </CardHeader>
              <CardContent>
                <DigitHeatmap prices={ticks.map((t) => t.quote)} selectedDigits={[]} />
              </CardContent>
            </Card>

            {/* Last Digits */}
            <Card className="bg-card">
              <CardHeader className="py-3">
                <CardTitle className="text-sm">Last 50 Digits</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-1">
                  {lastDigits.slice(-50).map((digit, i) => (
                    <span
                      key={i}
                      className={`w-8 h-8 flex items-center justify-center rounded text-sm font-mono ${
                        digit % 2 === 0 ? "bg-blue-500/20 text-blue-400" : "bg-orange-500/20 text-orange-400"
                      }`}
                    >
                      {digit}
                    </span>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* Prediction */}
            {prediction && (
              <Card className="border-primary/50 bg-primary/5">
                <CardContent className="py-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <Target className="h-8 w-8 text-primary" />
                      <div>
                        <div className="text-sm text-muted-foreground">Prediction</div>
                        <div className="text-xl font-bold">
                          {prediction.type}
                          {prediction.digit !== undefined && ` (${prediction.digit})`}
                        </div>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-sm text-muted-foreground">Confidence</div>
                      <div className="text-2xl font-bold text-primary">{prediction.confidence.toFixed(0)}%</div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>

          {/* Stats & History */}
          <div className="space-y-4">
            <Card className="bg-card">
              <CardHeader className="py-3">
                <CardTitle className="text-sm">Session Stats</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Total Trades</span>
                  <span className="font-semibold">{trades.length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Win Rate</span>
                  <span className={`font-semibold ${winRate >= 50 ? "text-green-500" : "text-red-500"}`}>
                    {winRate.toFixed(1)}%
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Profit/Loss</span>
                  <span className={`font-semibold ${totalProfit >= 0 ? "text-green-500" : "text-red-500"}`}>
                    {totalProfit >= 0 ? "+" : ""}
                    {totalProfit.toFixed(2)}
                  </span>
                </div>
              </CardContent>
            </Card>

            <Card className="bg-card">
              <CardHeader className="py-3">
                <CardTitle className="text-sm">Trade History</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <div className="max-h-[300px] overflow-y-auto">
                  {trades.map((trade) => (
                    <div key={trade.id} className="flex items-center justify-between p-2 border-t border-border">
                      <Badge
                        className={
                          trade.status === "won"
                            ? "bg-green-600"
                            : trade.status === "lost"
                              ? "bg-red-600"
                              : "bg-yellow-600"
                        }
                      >
                        {trade.type}
                      </Badge>
                      <span className="text-sm">${trade.amount.toFixed(2)}</span>
                      <span className={trade.profit >= 0 ? "text-green-500" : "text-red-500"}>
                        {trade.profit >= 0 ? "+" : ""}
                        {trade.profit.toFixed(2)}
                      </span>
                    </div>
                  ))}
                  {trades.length === 0 && <p className="text-center text-muted-foreground p-4">No trades yet</p>}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </main>
    </div>
  )
}
