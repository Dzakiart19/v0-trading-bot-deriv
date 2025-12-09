"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Slider } from "@/components/ui/slider"
import { TradingChart } from "@/components/trading-chart"
import { type DerivAPI, type TickData, createDerivAPI } from "@/lib/deriv-api"
import { ArrowLeft, Wifi, WifiOff, Zap, TrendingUp, DollarSign, Percent, Play, Square } from "lucide-react"

const ACCUMULATOR_SYMBOLS = [
  { value: "R_10", label: "Volatility 10" },
  { value: "R_25", label: "Volatility 25" },
  { value: "R_50", label: "Volatility 50" },
  { value: "R_75", label: "Volatility 75" },
  { value: "R_100", label: "Volatility 100" },
]

const GROWTH_RATES = [
  { value: "0.01", label: "1%" },
  { value: "0.02", label: "2%" },
  { value: "0.03", label: "3%" },
  { value: "0.04", label: "4%" },
  { value: "0.05", label: "5%" },
]

export default function AMTPage() {
  const router = useRouter()
  const [api, setApi] = useState<DerivAPI | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [symbol, setSymbol] = useState("R_50")
  const [ticks, setTicks] = useState<TickData[]>([])
  const [balance, setBalance] = useState(0)
  const [currency, setCurrency] = useState("USD")
  const [totalProfit, setTotalProfit] = useState(0)

  // Trading config
  const [stake, setStake] = useState(10)
  const [growthRate, setGrowthRate] = useState("0.03")
  const [takeProfitPercent, setTakeProfitPercent] = useState(50)
  const [isAutoRunning, setIsAutoRunning] = useState(false)

  // Active contract
  const [activeContract, setActiveContract] = useState<{
    id: number
    currentValue: number
    profit: number
    tickCount: number
    growthRate: number
  } | null>(null)

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

        derivApi.getTickHistory(symbol, 100).then(setTicks)
        derivApi.subscribeTicks(symbol, (tick) => {
          setTicks((prev) => [...prev.slice(-99), tick])
        })
      })
      .catch(() => {
        router.push("/")
      })

    return () => {
      derivApi.disconnect()
    }
  }, [router])

  useEffect(() => {
    if (!api || !isConnected) return

    api.unsubscribeTicks(symbol).then(() => {
      api.getTickHistory(symbol, 100).then(setTicks)
      api.subscribeTicks(symbol, (tick) => {
        setTicks((prev) => [...prev.slice(-99), tick])
      })
    })
  }, [symbol, api, isConnected])

  const handleBuyAccumulator = async () => {
    if (!api) return

    try {
      const proposal = await api.getProposal({
        contract_type: "ACCU",
        symbol,
        duration: 230,
        duration_unit: "t",
        amount: stake,
        basis: "stake",
        barrier: growthRate,
      })

      const result = await api.buyContract(proposal.id, proposal.ask_price)

      setActiveContract({
        id: result.contract_id,
        currentValue: stake,
        profit: 0,
        tickCount: 0,
        growthRate: Number.parseFloat(growthRate) * 100,
      })

      const { balance: newBalance } = await api.getBalance()
      setBalance(newBalance)

      // Monitor contract
      const checkResult = setInterval(async () => {
        const update = await api.getContractUpdate(result.contract_id)

        if (update.status === "open") {
          setActiveContract((prev) =>
            prev
              ? {
                  ...prev,
                  currentValue: update.payout,
                  profit: update.profit,
                  tickCount: prev.tickCount + 1,
                }
              : null,
          )

          // Auto take profit
          const profitPercent = (update.profit / stake) * 100
          if (profitPercent >= takeProfitPercent) {
            // Would call sell here
            clearInterval(checkResult)
            setActiveContract(null)
            setTotalProfit((prev) => prev + update.profit)
            const { balance: finalBalance } = await api.getBalance()
            setBalance(finalBalance)
          }
        } else {
          clearInterval(checkResult)
          setActiveContract(null)
          setTotalProfit((prev) => prev + update.profit)
          const { balance: finalBalance } = await api.getBalance()
          setBalance(finalBalance)
        }
      }, 1000)
    } catch (error) {
      console.error("Trade error:", error)
    }
  }

  // Calculate potential profit at different tick counts
  const profitProjection = Array.from({ length: 10 }, (_, i) => {
    const ticks = (i + 1) * 10
    const rate = Number.parseFloat(growthRate)
    const value = stake * Math.pow(1 + rate, ticks)
    return { ticks, value: value.toFixed(2), profit: (value - stake).toFixed(2) }
  })

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b bg-card sticky top-0 z-10">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" onClick={() => router.push("/")}>
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div>
              <h1 className="text-lg font-bold">AMT Accumulator</h1>
              <p className="text-xs text-muted-foreground">Growth Rate Trading</p>
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
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 space-y-4">
            {/* Symbol & Price */}
            <div className="flex items-center gap-4">
              <Select value={symbol} onValueChange={setSymbol}>
                <SelectTrigger className="w-[200px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ACCUMULATOR_SYMBOLS.map((s) => (
                    <SelectItem key={s.value} value={s.value}>
                      {s.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {ticks.length > 0 && (
                <span className="text-2xl font-mono font-bold">{ticks[ticks.length - 1]?.quote.toFixed(5)}</span>
              )}
            </div>

            {/* Chart */}
            <Card>
              <CardContent className="p-4">
                <TradingChart ticks={ticks} height={300} lineColor="#f59e0b" />
              </CardContent>
            </Card>

            {/* Active Contract */}
            {activeContract && (
              <Card className="border-orange-500/50 bg-orange-500/5">
                <CardHeader className="py-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Zap className="h-4 w-4 text-orange-500" />
                      Active Accumulator
                    </CardTitle>
                    <Badge variant="outline">{activeContract.tickCount} ticks</Badge>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-3 gap-4 text-center">
                    <div>
                      <div className="text-xs text-muted-foreground">Current Value</div>
                      <div className="text-xl font-bold">${activeContract.currentValue.toFixed(2)}</div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground">Profit</div>
                      <div
                        className={`text-xl font-bold ${activeContract.profit >= 0 ? "text-green-500" : "text-red-500"}`}
                      >
                        {activeContract.profit >= 0 ? "+" : ""}${activeContract.profit.toFixed(2)}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground">Growth Rate</div>
                      <div className="text-xl font-bold text-orange-500">{activeContract.growthRate}%</div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Profit Projection */}
            <Card>
              <CardHeader className="py-3">
                <CardTitle className="text-sm">Profit Projection ({growthRate}% per tick)</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b">
                        <th className="text-left p-2">Ticks</th>
                        {profitProjection.map((p) => (
                          <th key={p.ticks} className="text-center p-2">
                            {p.ticks}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      <tr className="border-b">
                        <td className="p-2 text-muted-foreground">Value</td>
                        {profitProjection.map((p) => (
                          <td key={p.ticks} className="text-center p-2">
                            ${p.value}
                          </td>
                        ))}
                      </tr>
                      <tr>
                        <td className="p-2 text-muted-foreground">Profit</td>
                        {profitProjection.map((p) => (
                          <td key={p.ticks} className="text-center p-2 text-green-500">
                            +${p.profit}
                          </td>
                        ))}
                      </tr>
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Trade Panel */}
          <div className="space-y-4">
            <Card>
              <CardHeader className="py-3">
                <CardTitle className="text-lg">Accumulator Config</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Stake */}
                <div className="space-y-2">
                  <Label className="flex items-center gap-2">
                    <DollarSign className="h-4 w-4" />
                    Stake ({currency})
                  </Label>
                  <Input
                    type="number"
                    value={stake}
                    onChange={(e) => setStake(Number.parseFloat(e.target.value) || 0)}
                    min={1}
                    step={1}
                  />
                </div>

                {/* Quick Stakes */}
                <div className="flex gap-2">
                  {[5, 10, 25, 50].map((val) => (
                    <Button
                      key={val}
                      variant={stake === val ? "default" : "outline"}
                      size="sm"
                      className="flex-1"
                      onClick={() => setStake(val)}
                    >
                      ${val}
                    </Button>
                  ))}
                </div>

                {/* Growth Rate */}
                <div className="space-y-2">
                  <Label className="flex items-center gap-2">
                    <TrendingUp className="h-4 w-4" />
                    Growth Rate
                  </Label>
                  <Select value={growthRate} onValueChange={setGrowthRate}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {GROWTH_RATES.map((r) => (
                        <SelectItem key={r.value} value={r.value}>
                          {r.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {/* Take Profit */}
                <div className="space-y-2">
                  <Label className="flex items-center justify-between">
                    <span className="flex items-center gap-2">
                      <Percent className="h-4 w-4" />
                      Take Profit
                    </span>
                    <span className="text-primary font-semibold">{takeProfitPercent}%</span>
                  </Label>
                  <Slider
                    value={[takeProfitPercent]}
                    onValueChange={([v]) => setTakeProfitPercent(v)}
                    min={10}
                    max={200}
                    step={10}
                  />
                </div>

                {/* Buy Button */}
                <Button
                  size="lg"
                  className="w-full h-14 bg-orange-600 hover:bg-orange-700"
                  onClick={handleBuyAccumulator}
                  disabled={!!activeContract || isAutoRunning}
                >
                  <Zap className="h-5 w-5 mr-2" />
                  BUY ACCUMULATOR
                </Button>

                {/* Auto Button */}
                <Button
                  size="lg"
                  className={`w-full h-12 ${isAutoRunning ? "bg-red-600 hover:bg-red-700" : "bg-blue-600 hover:bg-blue-700"}`}
                  onClick={() => setIsAutoRunning(!isAutoRunning)}
                >
                  {isAutoRunning ? (
                    <>
                      <Square className="h-5 w-5 mr-2" />
                      STOP AUTO
                    </>
                  ) : (
                    <>
                      <Play className="h-5 w-5 mr-2" />
                      START AUTO
                    </>
                  )}
                </Button>
              </CardContent>
            </Card>
          </div>
        </div>
      </main>
    </div>
  )
}
