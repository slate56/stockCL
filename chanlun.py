# 导入函数库
import jqdata


class trade_stat():
    def __init__(self):
        self.trade_total_count = 0
        self.trade_success_count = 0
        self.statis = {'win': [], 'loss': []}

    def reset(self):
        self.trade_total_count = 0
        self.trade_success_count = 0
        self.statis = {'win': [], 'loss': []}

    # 记录交易次数便于统计胜率
    # 卖出成功后针对卖出的量进行盈亏统计
    def watch(self, stock, sold_amount, avg_cost, cur_price):
        self.trade_total_count += 1
        current_value = sold_amount * cur_price
        cost = sold_amount * avg_cost

        percent = round((current_value - cost) / cost * 100, 2)
        if current_value > cost:
            self.trade_success_count += 1
            win = [stock, percent]
            self.statis['win'].append(win)
        else:
            loss = [stock, percent]
            self.statis['loss'].append(loss)

    def report(self, context):
        cash = context.portfolio.cash
        totol_value = context.portfolio.portfolio_value
        position = 1 - cash/totol_value
        log.info("收盘后持仓概况:%s" % str(list(context.portfolio.positions)))
        log.info("仓位概况:%.2f" % position)
        self.print_win_rate(context.current_dt.strftime("%Y-%m-%d"), context.current_dt.strftime("%Y-%m-%d"), context)

    # 打印胜率
    def print_win_rate(self, current_date, print_date, context):
        if str(current_date) == str(print_date):
            win_rate = 0
            if 0 < self.trade_total_count and 0 < self.trade_success_count:
                win_rate = round(self.trade_success_count / float(self.trade_total_count), 3)

            most_win = self.statis_most_win_percent()
            most_loss = self.statis_most_loss_percent()
            starting_cash = context.portfolio.starting_cash
            total_profit = self.statis_total_profit(context)
            if len(most_win)==0 or len(most_loss)==0:
                return

            print "-"
            print '------------绩效报表------------'
            print '交易次数: {0}, 盈利次数: {1}, 胜率: {2}'.format(self.trade_total_count, self.trade_success_count, str(win_rate * 100) + str('%'))
            print '单次盈利最高: {0}, 盈利比例: {1}%'.format(most_win['stock'], most_win['value'])
            print '单次亏损最高: {0}, 亏损比例: {1}%'.format(most_loss['stock'], most_loss['value'])
            print '总资产: {0}, 本金: {1}, 盈利: {2}, 盈亏比率：{3}%'.format(starting_cash + total_profit, starting_cash, total_profit, total_profit / starting_cash * 100)
            print '--------------------------------'
            print "-"

    # 统计单次盈利最高的股票
    def statis_most_win_percent(self):
        result = {}
        for statis in self.statis['win']:
            if {} == result:
                result['stock'] = statis[0]
                result['value'] = statis[1]
            else:
                if statis[1] > result['value']:
                    result['stock'] = statis[0]
                    result['value'] = statis[1]

        return result

    # 统计单次亏损最高的股票
    def statis_most_loss_percent(self):
        result = {}
        for statis in self.statis['loss']:
            if {} == result:
                result['stock'] = statis[0]
                result['value'] = statis[1]
            else:
                if statis[1] < result['value']:
                    result['stock'] = statis[0]
                    result['value'] = statis[1]

        return result

    # 统计总盈利金额
    def statis_total_profit(self, context):
        return context.portfolio.portfolio_value - context.portfolio.starting_cash


def get_blacklist():
    # 黑名单一览表，更新时间 2016.7.10 by 沙米
    # 科恒股份、太空板业，一旦2016年继续亏损，直接面临暂停上市风险
    blacklist = ["600656.XSHG","300372.XSHE","600403.XSHG","600421.XSHG","600733.XSHG","300399.XSHE",
                 "600145.XSHG","002679.XSHE","000020.XSHE","002330.XSHE","300117.XSHE","300135.XSHE",
                 "002566.XSHE","002119.XSHE","300208.XSHE","002237.XSHE","002608.XSHE","000691.XSHE",
                 "002694.XSHE","002715.XSHE","002211.XSHE","000788.XSHE","300380.XSHE","300028.XSHE",
                 "000668.XSHE","300033.XSHE","300126.XSHE","300340.XSHE","300344.XSHE","002473.XSHE"]
    return blacklist

def before_trading_start(context):
    g.stocks_pool = getStockPool()
    log.info("---------------------------------------------")
    #log.info("==> before trading start @ %s", str(context.current_dt))

    # 盘前就判断三黑鸦状态，因为判断的数据为前4日
    g.is_last_day_3_black_crows = is_3_black_crows(g.index_4_stop_loss_by_3_black_crows)
    if g.is_last_day_3_black_crows:
        log.info("==> 前4日已经构成三黑鸦形态")
    pass

def after_trading_end(context):
    #log.info("==> after trading end @ %s", str(context.current_dt))
    g.trade_stat.report(context)

    reset_day_param()

    # 得到当前未完成订单
    orders = get_open_orders()
    for _order in orders.values():
        log.info("canceled uncompleted order: %s" %(_order.order_id))
    pass

# 初始化函数，设定基准等等
# 初始函数开始运行且全局只运行一次
def initialize(context):
    import datetime
    today = datetime.datetime.today().strftime("%Y-%m-%d")
    print(today)
    log.info("==> initialize @ %s", str(context.current_dt))

    # 设置手续费率
    set_commission(PerTrade(buy_cost=0.0003, sell_cost=0.0013, min_cost=5))
    # 设置基准指数：沪深300指数 '000300.XSHG'
    set_benchmark('000300.XSHG')
    # 设定滑点为百分比
    # 没有调用set_slippage函数, 系统默认的滑点是PriceRelatedSlippage(0.00246)
    #set_slippage(PriceRelatedSlippage(0.004))
    # 使用真实价格回测(模拟盘推荐如此，回测请注释)
    set_option('use_real_price', True)

    # 加载统计模块
    g.trade_stat = trade_stat()

    # 配置策略参数
    # 此配置主要为之前的小市值策略，保证之前的收益回撤
    # 如果想要更改，最好新建个函数，调整参数测试其他策略
    # 10日调仓
    # 关闭大盘三乌鸦及高低价止损
    # 关闭个股止盈止损
    # 关闭选股评分
    set_param()

    g.total_shares = get_fundamentals(query(
        valuation.code, valuation.capitalization), date=today)
    g.total_codes = list(g.total_shares["code"])
    # 调仓日计数器，单位：日
    g.day_count = 0

    # 缓存股票持仓后的最高价
    g.last_high = {}

    # 如下参数不能更改
    if g.is_market_stop_loss_by_price:
        # 记录当日是否满足大盘价格止损条件，每日盘后重置
        g.is_day_stop_loss_by_price = False

    # 缓存三黑鸦判断状态
    g.is_last_day_3_black_crows = False
    if g.is_market_stop_loss_by_3_black_crows:
        g.cur_drop_minute_count = 0

    if g.is_rank_stock:
        if g.rank_stock_count > g.pick_stock_count:
            g.rank_stock_count = g.pick_stock_count

    if g.is_stock_stop_loss or g.is_stock_stop_profit:
        # 缓存当日个股250天内最大的3日涨幅，避免当日反复获取，每日盘后清空
        g.pct_change = {}

    if g.is_market_stop_loss_by_28_index:
        g.minute_count_28index_drop = 0

    # 打印策略参数
    log_param()


    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
      # 开盘时运行
    run_daily(market_open, time='open', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')

def set_param():
    # 调仓频率，单位：日
    g.period = 3
    # 配置调仓时间（24小时分钟制）
    g.adjust_position_hour = 14
    g.adjust_position_minute = 50

    # 配置选股参数

    # 备选股票数目
    g.pick_stock_count = 100

    # 配置选股参数
    # 是否根据PE选股
    g.pick_by_pe = False
    # 如果根据PE选股，则配置最大和最小PE值
    if g.pick_by_pe:
        g.max_pe = 200
        g.min_pe = 0

    # 是否根据EPS选股
    g.pick_by_eps = False
    # 配置选股最小EPS值
    if g.pick_by_eps:
        g.min_eps = 0

    # 配置是否过滤创业板股票
    g.filter_gem = True
    # 配置是否过滤黑名单股票，回测建议关闭，模拟运行时开启
    g.filter_blacklist = False

    # 是否对股票评分
    g.is_rank_stock = True
    if g.is_rank_stock:
        # 参与评分的股票数目
        g.rank_stock_count = 20

    # 买入股票数目
    g.buy_stock_count = 3

    # 配置二八指数
    g.index2 = '000300.XSHG'  # 沪深300指数，表示二，大盘股
    g.index8 = '000905.XSHG'  # 中证500指数，表示八，小盘股
    #g.index2 = '000016.XSHG'  # 上证50指数
    #g.index8 = '399333.XSHE'  # 中小板R指数
    #g.index8 = '399006.XSHE'  # 创业板指数

    # 判定调仓的二八指数20日增幅
    #g.index_growth_rate = 0.00
    g.index_growth_rate = 0.01

    # 配置是否根据大盘历史价格止损
    # 大盘指数前130日内最高价超过最低价2倍，则清仓止损
    # 注：关闭此止损，收益增加，但回撤会增加
    g.is_market_stop_loss_by_price = True
    if g.is_market_stop_loss_by_price:
        # 配置价格止损判定指数，默认为上证指数，可修改为其他指数
        g.index_4_stop_loss_by_price = '000001.XSHG'

    # 配置三黑鸦判定指数，默认为上证指数，可修改为其他指数
    g.index_4_stop_loss_by_3_black_crows = '000001.XSHG'

    # 配置是否开启大盘三黑鸦止损
    # 个人认为针对大盘判断三黑鸦效果并不好，首先有效三只乌鸦难以判断，准确率实际来看也不好，
    # 其次，分析历史行情看一般大盘出现三只乌鸦的时候，已经严重滞后了，使用其他止损方式可能会更好
    g.is_market_stop_loss_by_3_black_crows = True
    if g.is_market_stop_loss_by_3_black_crows:
        g.dst_drop_minute_count = 60

    # 是否根据28指数值实时进行止损
    g.is_market_stop_loss_by_28_index = False
    if g.is_market_stop_loss_by_28_index:
        # 配置当日28指数连续为跌的分钟计数达到指定值则止损
        g.dst_minute_count_28index_drop = 120

    # 配置是否个股止损
    g.is_stock_stop_loss = False
    # 配置是否个股止盈
    g.is_stock_stop_profit = False

def log_param():
    log.info("调仓日频率: %d日" %(g.period))
    log.info("调仓时间: %s:%s" %(g.adjust_position_hour, g.adjust_position_minute))

    log.info("备选股票数目: %d" %(g.pick_stock_count))

    log.info("是否根据PE选股: %s" %(g.pick_by_pe))
    if g.pick_by_pe:
        log.info("选股最大PE: %s" %(g.max_pe))
        log.info("选股最小PE: %s" %(g.min_pe))

    log.info("是否根据EPS选股: %s" %(g.pick_by_eps))
    if g.pick_by_eps:
        log.info("选股最小EPS: %s" %(g.min_eps))

    log.info("是否过滤创业板股票: %s" %(g.filter_gem))
    log.info("是否过滤黑名单股票: %s" %(g.filter_blacklist))
    if g.filter_blacklist:
        log.info("当前股票黑名单：%s" %str(get_blacklist()))

    log.info("是否对股票评分选股: %s" %(g.is_rank_stock))
    if g.is_rank_stock:
        log.info("评分备选股票数目: %d" %(g.rank_stock_count))

    log.info("买入股票数目: %d" %(g.buy_stock_count))

    log.info("二八指数之二: %s - %s" %(g.index2, get_security_info(g.index2).display_name))
    log.info("二八指数之八: %s - %s" %(g.index8, get_security_info(g.index8).display_name))
    log.info("判定调仓的二八指数20日增幅: %.1f%%" %(g.index_growth_rate*100))

    log.info("是否开启大盘历史高低价格止损: %s" %(g.is_market_stop_loss_by_price))
    if g.is_market_stop_loss_by_price:
        log.info("大盘价格止损判定指数: %s - %s" %(g.index_4_stop_loss_by_price, get_security_info(g.index_4_stop_loss_by_price).display_name))

    log.info("大盘三黑鸦止损判定指数: %s - %s" %(g.index_4_stop_loss_by_3_black_crows, get_security_info(g.index_4_stop_loss_by_3_black_crows).display_name))
    log.info("是否开启大盘三黑鸦止损: %s" %(g.is_market_stop_loss_by_3_black_crows))
    if g.is_market_stop_loss_by_3_black_crows:
        log.info("三黑鸦止损开启需要当日大盘为跌的分钟计数达到: %d" %(g.dst_drop_minute_count))

    log.info("是否根据28指数值实时进行止损: %s" %(g.is_market_stop_loss_by_28_index))
    if g.is_market_stop_loss_by_28_index:
        log.info("根据28指数止损需要当日28指数连续为跌的分钟计数达到: %d" %(g.dst_minute_count_28index_drop))

    log.info("是否开启个股止损: %s" %(g.is_stock_stop_loss))
    log.info("是否开启个股止盈: %s" %(g.is_stock_stop_profit))


## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))

    # 给微信发送消息（添加模拟交易，并绑定微信生效）
    send_message('美好的一天~')

    # 要操作的股票：平安银行（g.为全局变量）
    g.security = '000001.XSHE'

## 开盘时运行函数
def market_open(context):
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    security = g.security
    # 获取股票的收盘价
    close_data = attribute_history(security, 5, '1d', ['close'])
    # 取得过去五天的平均价格
    MA5 = close_data['close'].mean()
    # 取得上一时间点价格
    current_price = close_data['close'][-1]
    # 取得当前的现金
    cash = context.portfolio.available_cash

    # 如果上一时间点价格高出五天平均价1%, 则全仓买入
    if current_price > 1.01*MA5:
        # 记录这次买入
        log.info("价格高于均价 1%%, 买入 %s" % (security))
        # 用所有 cash 买入股票
        order_value(security, cash)
    # 如果上一时间点价格低于五天平均价, 则空仓卖出
    elif current_price < MA5 and context.portfolio.positions[security].closeable_amount > 0:
        # 记录这次卖出
        log.info("价格低于均价, 卖出 %s" % (security))
        # 卖出所有股票,使这只股票的最终持有量为0
        order_target(security, 0)

## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')
