
autoidx 12

attribute \src "acyclic.sv:13.1-21.10"
attribute \keep 1
module \subm

  attribute \src "acyclic.sv:15.24-15.25"
  wire width 5 output 2 \y

  attribute \src "acyclic.sv:14.23-14.24"
  wire width 5 input 1 \x

  attribute \src "acyclic.sv:19.7-19.36"
  wire \subm_assert1_EN

  attribute \src "acyclic.sv:18.12-18.17"
  wire $gt$acyclic.sv:18$8_Y

  attribute \src "acyclic.sv:19.29-19.35"
  wire $ge$acyclic.sv:19$10_Y

  attribute \src "acyclic.sv:19.7-19.36"
  attribute \keep 1
  cell $check \subm_assert1
    parameter \TRG_WIDTH 0
    parameter \TRG_POLARITY 0'x
    parameter \TRG_ENABLE 0
    parameter \PRIORITY 32'11111111111111111111111111111111
    parameter \FORMAT ""
    parameter \FLAVOR "assert"
    parameter \ARGS_WIDTH 0
    connect \TRG { }
    connect \EN 1'1
    connect \ARGS { }
    connect \A $ge$acyclic.sv:19$10_Y
  end

  attribute \src "acyclic.sv:18.11-18.30"
  cell $mux $ternary$acyclic.sv:18$9
    parameter \WIDTH 5
    connect \Y \y
    connect \S $gt$acyclic.sv:18$8_Y
    connect \B \x
    connect \A 5'00010
  end

  attribute \src "acyclic.sv:18.12-18.17"
  cell $gt $gt$acyclic.sv:18$8
    parameter \Y_WIDTH 1
    parameter \B_WIDTH 2
    parameter \B_SIGNED 0
    parameter \A_WIDTH 5
    parameter \A_SIGNED 0
    connect \Y $gt$acyclic.sv:18$8_Y
    connect \B 2'10
    connect \A \x
  end

  attribute \src "acyclic.sv:19.29-19.35"
  cell $ge $ge$acyclic.sv:19$10
    parameter \Y_WIDTH 1
    parameter \B_WIDTH 2
    parameter \B_SIGNED 0
    parameter \A_WIDTH 5
    parameter \A_SIGNED 0
    connect \Y $ge$acyclic.sv:19$10_Y
    connect \B 2'10
    connect \A \y
  end

  connect \subm_assert1_EN 1'1
end

attribute \src "acyclic.sv:1.1-11.10"
attribute \top 1
attribute \keep 1
module \acyclic

  attribute \src "acyclic.sv:3.22-3.23"
  wire width 5 output 2 \z

  attribute \src "acyclic.sv:4.15-4.16"
  wire width 5 \y

  attribute \src "acyclic.sv:2.21-2.22"
  wire width 5 input 1 \x

  attribute \src "acyclic.sv:8.5-8.36"
  wire \acyclic_assert1_EN

  attribute \src "acyclic.sv:9.10-9.16"
  wire $lt$acyclic.sv:9$3_Y

  attribute \src "acyclic.sv:8.29-8.35"
  wire $ge$acyclic.sv:8$2_Y

  attribute \src "acyclic.sv:9.24-9.27"
  wire width 32 $auto$wreduce.cc:513:run$11

  attribute \src "acyclic.sv:6.8-6.23"
  attribute \module_not_derived 1
  cell \subm \s
    connect \y \y
    connect \x \x
  end

  attribute \src "acyclic.sv:8.5-8.36"
  attribute \keep 1
  cell $check \acyclic_assert1
    parameter \TRG_WIDTH 0
    parameter \TRG_POLARITY 0'x
    parameter \TRG_ENABLE 0
    parameter \PRIORITY 32'11111111111111111111111111111111
    parameter \FORMAT ""
    parameter \FLAVOR "assert"
    parameter \ARGS_WIDTH 0
    connect \TRG { }
    connect \EN 1'1
    connect \ARGS { }
    connect \A $ge$acyclic.sv:8$2_Y
  end

  attribute \src "acyclic.sv:9.9-9.27"
  cell $mux $ternary$acyclic.sv:9$6
    parameter \WIDTH 5
    connect \Y \z
    connect \S $lt$acyclic.sv:9$3_Y
    connect \B \y
    connect \A $auto$wreduce.cc:513:run$11 [4:0]
  end

  attribute \src "acyclic.sv:9.24-9.27"
  cell $sub $sub$acyclic.sv:9$4
    parameter \Y_WIDTH 5
    parameter \B_WIDTH 2
    parameter \B_SIGNED 0
    parameter \A_WIDTH 5
    parameter \A_SIGNED 0
    connect \Y $auto$wreduce.cc:513:run$11 [4:0]
    connect \B 2'10
    connect \A \y
  end

  attribute \src "acyclic.sv:9.10-9.16"
  cell $lt $lt$acyclic.sv:9$3
    parameter \Y_WIDTH 1
    parameter \B_WIDTH 4
    parameter \B_SIGNED 0
    parameter \A_WIDTH 5
    parameter \A_SIGNED 0
    connect \Y $lt$acyclic.sv:9$3_Y
    connect \B 4'1101
    connect \A \y
  end

  attribute \src "acyclic.sv:8.29-8.35"
  cell $ge $ge$acyclic.sv:8$2
    parameter \Y_WIDTH 1
    parameter \B_WIDTH 2
    parameter \B_SIGNED 0
    parameter \A_WIDTH 5
    parameter \A_SIGNED 0
    connect \Y $ge$acyclic.sv:8$2_Y
    connect \B 2'10
    connect \A \z
  end

  connect \acyclic_assert1_EN 1'1
  connect $auto$wreduce.cc:513:run$11 [31:6] { $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] $auto$wreduce.cc:513:run$11 [5] }
end

